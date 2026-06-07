"""
transfer.py — External Drive Transfer Module

Rsyncs both backup directories (files and snapshots) to the external
drive configured in config.yaml.

Behaviour:
    - Checks the drive is mounted before attempting transfer
    - If drive is not mounted — logs a warning and skips gracefully
    - Does not fail the overall job if the drive is absent
    - Uses rsync for efficient incremental transfer (only copies changes)

rsync flags used:
    -a  archive mode — preserves permissions, timestamps, symlinks
    -v  verbose — logs each file transferred at DEBUG level
    --delete  removes files from destination that no longer exist in source
              keeps the external drive in sync with rotation policy

Called by backup.py after rotate.py completes.
Result is passed to notify.py for inclusion in the email report.
"""

import subprocess
from pathlib import Path

from logger import get_logger, log_section, log_success, log_failure, log_warning


# ---------------------------
# Helpers
# ---------------------------

def is_mounted(path: str) -> bool:
    """
    Check whether a path is an active mount point.

    Uses Path.is_mount() which checks the OS mount table directly —
    more reliable than just checking if the directory exists,
    since the directory may exist but the drive not be plugged in.
    """
    return Path(path).exists() and Path(path).is_mount()


def rsync(source: str, destination: str, logger) -> None:
    """
    Run rsync from source to destination.

    Args:
        source      : Directory to sync from
        destination : Directory to sync to (on external drive)
        logger      : Shared logger instance

    Raises:
        subprocess.CalledProcessError if rsync exits with non-zero code
    """
    cmd = [
        "rsync",
        "-av",          # archive + verbose
        "--delete",     # mirror rotation — remove files deleted from source
        source,
        destination,
    ]

    logger.debug(f"  Running: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
    )

    # Log each transferred file at DEBUG level — visible in backup.log
    # but not printed to terminal during cron runs
    for line in result.stdout.splitlines():
        logger.debug(f"  rsync: {line}")


# ---------------------------
# Core — called by backup.py
# ---------------------------

def run(cfg: dict) -> dict:
    """
    Transfer both backup directories to the external drive.

    Args:
        cfg : Full config dict loaded from config.yaml by backup.py

    Returns:
        result dict — {
            passed      : bool — True if transfer completed or was intentionally skipped
            status      : str  — Human readable status for the email report
            drive_path  : str  — Configured drive mount path
            synced      : list — Directories successfully synced
            error       : str  — Error message if transfer failed, else None
        }
    """
    log_path = cfg.get("logging", {}).get(
        "log_file", "/var/log/backup_tool/backup.log")
    logger = get_logger(log_path)

    log_section(logger, "External Drive Transfer")

    result = {
        "passed": False,
        "status": "Not started",
        "drive_path": "N/A",
        "synced": [],
        "error": None,
    }

    try:
        transfer_cfg = cfg.get("transfer", {})

        # --- Check transfer is enabled --------------------
        if not transfer_cfg.get("enabled", True):
            logger.info("Transfer is disabled in config — skipping")
            result["passed"] = True
            result["status"] = "Disabled in config"
            return result

        drive_path = transfer_cfg["drive_mount_path"]
        result["drive_path"] = drive_path

        # --- Check drive is mounted -----------------------
        if not is_mounted(drive_path):
            msg = (
                f"External drive not mounted at {drive_path} — "
                f"transfer skipped. Plug in the drive and run "
                f"transfer.py manually to sync."
            )
            log_warning(logger, msg)
            result["passed"] = True   # Skipped intentionally — not a failure
            result["status"] = f"Skipped — drive not mounted at {drive_path}"
            return result

        logger.info(f"Drive mounted : {drive_path}")

        file_cfg = cfg["file_backup"]
        snapshot_cfg = cfg["snapshot"]

        # --- Sync file backups ---------------------------
        file_src = file_cfg["destination"]
        file_dest = str(Path(drive_path) / "files")

        logger.info(f"Syncing files : {file_src} → {file_dest}")
        Path(file_dest).mkdir(parents=True, exist_ok=True)
        rsync(file_src, file_dest, logger)
        result["synced"].append(file_src)
        log_success(logger, f"Files synced  : {file_dest}")

        # --- Sync snapshots ---------------------------
        snap_src = snapshot_cfg["destination"]
        snap_dest = str(Path(drive_path) / "snapshots")

        logger.info(f"Syncing snaps : {snap_src} → {snap_dest}")
        Path(snap_dest).mkdir(parents=True, exist_ok=True)
        rsync(snap_src, snap_dest, logger)
        result["synced"].append(snap_src)
        log_success(logger, f"Snaps synced  : {snap_dest}")

        result["passed"] = True
        result["status"] = f"Synced to {drive_path}"
        log_success(logger, f"Transfer complete — {drive_path}")

    except subprocess.CalledProcessError as e:
        msg = f"rsync failed: {e.stderr.strip()}"
        log_failure(logger, msg)
        result["error"] = msg
        result["status"] = "Failed — rsync error"

    except KeyError as e:
        msg = f"Missing config key: {e}"
        log_failure(logger, msg)
        result["error"] = msg
        result["status"] = "Failed — config error"

    except OSError as e:
        msg = f"File system error: {e}"
        log_failure(logger, msg)
        result["error"] = msg
        result["status"] = "Failed — file system error"

    except Exception as e:
        msg = f"Unexpected error: {e}"
        log_failure(logger, msg)
        result["error"] = msg
        result["status"] = "Failed — unexpected error"

    return result
