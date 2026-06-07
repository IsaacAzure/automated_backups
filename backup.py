#!/usr/bin/env python3
"""
backup.py — Master Orchestrator

Single entry point for the entire backup pipeline.
Called nightly by anacron via /etc/cron.daily/backup_tool.

Pipeline order:
    1. Load config.yaml
    2. file_backup.py  — zip source directories
    3. snapshot.py     — btrfs snapshot → tar.gz
    4. verify.py       — integrity checks on both archives
    5. rotate.py       — enforce 7-day retention policy
    6. transfer.py     — rsync to external drive
    7. notify.py       — send HTML email report

Error handling:
    Each module returns a result dict — failures are recorded and
    passed to notify.py rather than crashing the pipeline.
    A top-level except ensures a failure email is always attempted
    even if something completely unexpected occurs.
"""

import sys
import os

# Ensure modules directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "modules"))

import yaml

from logger import get_logger, log_section, log_success, log_failure

from modules import (
    file_backup,
    snapshot,
    verify,
    rotate,
    transfer,
    notify,
)


# ─────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load config.yaml from the same directory as backup.py."""
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


# ─────────────────────────────────────────────────────────
# Empty result fallbacks
# Used when a stage fails to return a result at all
# ─────────────────────────────────────────────────────────

EMPTY_FILE_RESULT = {
    "passed": False, "archive_path": None,
    "total_files": 0, "skipped_files": [],
    "size_human": "N/A", "error": "Stage did not run",
}

EMPTY_SNAPSHOT_RESULT = {
    "passed": False, "archive_path": None,
    "size_human": "N/A", "error": "Stage did not run",
}

EMPTY_VERIFY_RESULT = {
    "passed": False,
    "zip_result": {"passed": False, "errors": ["Verify did not run"]},
    "tar_result": {"passed": False, "errors": ["Verify did not run"]},
}

EMPTY_ROTATE_RESULT = {
    "passed": False, "deleted_files": [],
    "deleted_snapshots": [], "retention_days": 7,
    "error": "Stage did not run",
}

EMPTY_TRANSFER_RESULT = {
    "passed": False, "status": "Did not run",
    "drive_path": "N/A", "synced": [], "error": "Stage did not run",
}


# ─────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────

def main() -> None:

    # ── Bootstrap logger before config loads ─────────────
    # Uses fallback path in case config itself fails to load
    logger = get_logger("/var/log/backup_tool/backup.log")

    # Initialise all results to empty fallbacks
    file_result     = EMPTY_FILE_RESULT
    snapshot_result = EMPTY_SNAPSHOT_RESULT
    verify_result   = EMPTY_VERIFY_RESULT
    rotate_result   = EMPTY_ROTATE_RESULT
    transfer_result = EMPTY_TRANSFER_RESULT
    cfg             = {}

    try:

        # ── Load config ───────────────────────────────────
        log_section(logger, "Backup Job Starting")
        cfg    = load_config()
        logger = get_logger(
            cfg.get("logging", {}).get("log_file", "/var/log/backup_tool/backup.log")
        )
        logger.info("Config loaded successfully")

        # ── Stage 1: File Backup ──────────────────────────
        file_result = file_backup.run(cfg)

        # ── Stage 2: System Snapshot ──────────────────────
        snapshot_result = snapshot.run(cfg)

        # ── Stage 3: Integrity Verification ──────────────
        verify_result = verify.run(cfg, file_result, snapshot_result)

        # ── Stage 4: Rotation ─────────────────────────────
        rotate_result = rotate.run(cfg)

        # ── Stage 5: External Drive Transfer ─────────────
        transfer_result = transfer.run(cfg)

    except FileNotFoundError as e:
        log_failure(logger, f"Config file not found: {e}")

    except yaml.YAMLError as e:
        log_failure(logger, f"Config file is invalid YAML: {e}")

    except Exception as e:
        log_failure(logger, f"Unexpected error in pipeline: {e}")

    finally:
        # ── Stage 6: Email Report ─────────────────────────
        # Always runs — even if the pipeline crashed above.
        # A failure report is the most important one to receive.
        log_section(logger, "Backup Job Complete")

        overall = all([
            file_result.get("passed",     False),
            snapshot_result.get("passed", False),
            verify_result.get("passed",   False),
            rotate_result.get("passed",   False),
        ])

        if overall:
            log_success(logger, "All stages passed")
        else:
            log_failure(logger, "One or more stages failed — check report")

        try:
            notify.run(
                cfg             = cfg,
                file_result     = file_result,
                snapshot_result = snapshot_result,
                verify_result   = verify_result,
                rotate_result   = rotate_result,
                transfer_result = transfer_result,
            )
        except Exception as e:
            log_failure(logger, f"Failed to send email report: {e}")

        logger.info("=" * 55)


if __name__ == "__main__":
    main()
