"""
System Snapshot Module

Creates a Btrfs snapshot of the root subvolume, archives it into a timestamped .tag.gz file.
Saves it to the configured destination and removes the raw snapshot form /.snapshots/ to keep things clean.

Requires root privileges - run with sudo or as root.
Called by backup.py as the second stage of the backup pipeline.

Vtrfs snapshot flow:
    1. btrfs subvolume snapshot / /.snapshots/backup_snap (create)
    2. tar -czf snapshot_TIMESTAMP.tar.gz /.snapshots/backup_snap (archive)
    3. btrfs subvolume delete /.snapshots/backup_snap        (cleanup)
 
Output example:
    /var/backups/backup_tool/snapshots/snapshot_2025-01-15_02-00-00.tar.gz

NOTE: /home is a separate Btrfs subvolume (ID 256) and is intentionally
excluded from this snapshot. Personal data under /home is covered by
file_backup.py. This snapshot targets the root subvolume (ID 257) only,
capturing system state, installed packages, and configuration.
To include /home, add it as a second subvolume in config.yaml.
"""

import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

from logger import get_logger, log_section, log_success, log_failure, log_warning


# ---------------------------
# Helpers
# ---------------------------

def format_bytes(size: int) -> str:
    """Convert a byte count into human readable string. e.g. 1,000,000 -> 1MB"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def run_command(cmd: list, logger) -> subprocess.CompletedProcess:
    """
    Run a shell commmand and return the result.
    Written to backup.log at DEBUG level."""
    logger.debug(f" Running: {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
    )

# ---------------------------
# Core Function
# ---------------------------


def run(cfg: dict) -> dict:
    """
    Execute the system snapshot stage.

    Creates a Btrfs snapshot of the root subvolume, archives it, cleans up the raw snapshot.
    Returns a result dict for use by verify.py and notify.py.

    Args:
        cfg: Full config dict loaded from config.yaml by backup.py.

    Returns:
        result dict — {
            passed        : bool  — True if snapshot and archive succeeded
            archive_path  : str   — absolute path to the .tar.gz file
            size_human    : str   — human readable archive size e.g. "4.7 GB"
            error         : str   — error message if job failed, else None
        }
    """
    log_path = cfg.get("logging", {}).get(
        "log_file", "/var/log/backup_tool/backup_tool.log")
    logger = get_logger(log_path)

    log_section(logger, "System Snaphot (Btrfs)")

    result = {
        "passed": False,
        "archive_path": None,
        "size_human": "0 B",
        "error": None,
    }

    # Track snapshot path for cleanup in finally block
    snapshot_path = None

    try:
        snap_cfg = cfg["snapshot"]
        btrfs_cfg = snap_cfg["btrfs"]
        subvolume = btrfs_cfg["subvolume"]           # /
        snapshot_dir = btrfs_cfg["snapshot_dir"]        # /.snapshots
        snap_name = btrfs_cfg["snapshot_name"]       # backup_snap
        dest_dir = snap_cfg["destination"]
        prefix = snap_cfg.get("archive_prefix", "snapshot")

        snapshot_path = Path(snapshot_dir) / snap_name

        # ── Build archive path ────────────────────────────
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archive_name = f"{prefix}_{timestamp}.tar.gz"
        archive_path = Path(dest_dir) / archive_name

        # Create destination and snapshot directories if missing
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        Path(snapshot_dir).mkdir(parents=True, exist_ok=True)

        logger.info(f"Subvolume    : {subvolume}")
        logger.info(f"Snapshot dir : {snapshot_dir}")
        logger.info(f"Destination  : {dest_dir}")
        logger.info(f"Archive      : {archive_name}")

        # ── Step 1: Create Btrfs snapshot ────────────────
        # If a snapshot with this name already exists (e.g. from a failed
        # previous run) delete it first to avoid errors
        if snapshot_path.exists():
            log_warning(
                logger, f"Stale snapshot found at {snapshot_path} — removing")
            run_command(["btrfs", "subvolume", "delete",
                        str(snapshot_path)], logger)

        logger.info(f"Creating Btrfs snapshot: {subvolume} → {snapshot_path}")
        run_command(
            ["btrfs", "subvolume", "snapshot", "-r",
                subvolume, str(snapshot_path)],
            logger,
        )
        # -r flag creates a read-only snapshot — safer for backup purposes
        log_success(logger, "Btrfs snapshot created")

        # ── Step 2: Archive snapshot to .tar.gz ──────────
        logger.info(f"Archiving snapshot → {archive_name}")

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(str(snapshot_path), arcname=snap_name)

        size_bytes = archive_path.stat().st_size
        size_human = format_bytes(size_bytes)

        result["passed"] = True
        result["archive_path"] = str(archive_path)
        result["size_human"] = size_human

        log_success(logger, f"Snapshot archived — {size_human}")

    except subprocess.CalledProcessError as e:
        msg = f"Btrfs command failed: {e.cmd} — {e.stderr.strip()}"
        log_failure(logger, msg)
        result["error"] = msg

    except OSError as e:
        msg = f"File system error: {e}"
        log_failure(logger, msg)
        result["error"] = msg

    except KeyError as e:
        msg = f"Missing config key: {e}"
        log_failure(logger, msg)
        result["error"] = msg

    except Exception as e:
        msg = f"Unexpected error: {e}"
        log_failure(logger, msg)
        result["error"] = msg

    finally:
        # ── Step 3: Always clean up raw snapshot ─────────
        # Runs whether the archive succeeded or failed.
        # Prevents stale snapshots building up in /.snapshots/
        if snapshot_path and snapshot_path.exists():
            try:
                run_command(
                    ["btrfs", "subvolume", "delete", str(snapshot_path)],
                    logger,
                )
                log_success(logger, f"Raw snapshot removed: {snapshot_path}")
            except subprocess.CalledProcessError as e:
                log_warning(
                    logger, f"Could not remove raw snapshot: {e.stderr.strip()}")

    return result
