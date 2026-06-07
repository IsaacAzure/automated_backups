"""
rotate.py — Backup Rotation Module

Enforces the 7-day retention policy configured in config.yaml.
Scans both the file backup and snapshot destination directories,
and deletes any archives older than retention_days.

Only deletes files matching the configured archive prefix to avoid
accidentally removing unrelated files in the destination directory.

Called by backup.py after verify.py completes.
Results are passed to notify.py for inclusion in the email report.
"""

from datetime import datetime, timedelta
from pathlib import Path

from logger import get_logger, log_section, log_success, log_warning


# ---------------------------
# Core — rotate a single directory
# ---------------------------

def rotate_directory(
    directory: str,
    prefix: str,
    extension: str,
    retention: int,
    logger,
) -> list:
    """
    Delete archives older than retention days in a single directory.

    Args:
        directory  : Path to scan e.g. /var/backups/backup_tool/files/
        prefix     : Archive prefix to match e.g. "backup" or "snapshot"
        extension  : File extension to match e.g. ".zip" or ".tar.gz"
        retention  : Number of days to keep archives
        logger     : Shared logger instance

    Returns:
        List of filenames that were deleted
    """
    deleted = []
    cutoff = datetime.now() - timedelta(days=retention)
    dir_path = Path(directory)

    logger.info(
        f"Scanning      : {directory}\n"
        f"  Prefix      : {prefix}\n"
        f"  Retention   : {retention} days\n"
        f"  Cutoff      : {cutoff.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # --- Check directory exists -------------------------
    if not dir_path.exists():
        log_warning(logger, f"Directory not found, skipping: {directory}")
        return deleted

    # --- Find matching archives ---------------------------
    # Matches files like: backup_2025-01-08_02-00-00.zip
    #                     snapshot_2025-01-08_02-00-00.tar.gz
    pattern = f"{prefix}_*{extension}"
    archives = sorted(dir_path.glob(pattern))

    if not archives:
        logger.info(f"  No archives found matching: {pattern}")
        return deleted

    # --- Check each archive against cutoff -----------------
    for archive in archives:
        modified_time = datetime.fromtimestamp(archive.stat().st_mtime)

        if modified_time < cutoff:
            try:
                archive.unlink()
                deleted.append(archive.name)
                logger.info(
                    f"  Deleted : {archive.name} "
                    f"(last modified {modified_time.strftime('%Y-%m-%d')})"
                )
            except OSError as e:
                log_warning(logger, f"  Could not delete {archive.name}: {e}")
        else:
            logger.debug(
                f"  Keeping : {archive.name} "
                f"(modified {modified_time.strftime('%Y-%m-%d')})"
            )

    return deleted


# ---------------------------
# Core — called by backup.py
# ---------------------------

def run(cfg: dict) -> dict:
    """
    Enforce the retention policy on both backup directories.

    Rotates file backup archives (.zip) and snapshot archives (.tar.gz)
    independently using their respective prefix and destination from config.

    Args:
        cfg : Full config dict loaded from config.yaml by backup.py

    Returns:
        result dict — {
            passed          : bool  — True if rotation completed without errors
            deleted_files   : list  — filenames deleted from files/
            deleted_snapshots: list — filenames deleted from snapshots/
            retention_days  : int   — retention setting used
            error           : str   — error message if job failed, else None
        }
    """
    log_path = cfg.get("logging", {}).get(
        "log_file", "/var/log/backup_tool/backup.log")
    logger = get_logger(log_path)

    log_section(logger, "Rotation Policy")

    result = {
        "passed": False,
        "deleted_files": [],
        "deleted_snapshots": [],
        "retention_days": 7,
        "error": None,
    }

    try:
        retention = cfg["retention"]["days"]
        result["retention_days"] = retention

        file_cfg = cfg["file_backup"]
        snapshot_cfg = cfg["snapshot"]

        # --- Rotate file backups --------------------------
        logger.info("File backup rotation:")
        result["deleted_files"] = rotate_directory(
            directory=file_cfg["destination"],
            prefix=file_cfg.get("archive_prefix", "backup"),
            extension=".zip",
            retention=retention,
            logger=logger,
        )

        # --- Rotate snapshots ---------------------------
        logger.info("Snapshot rotation:")
        result["deleted_snapshots"] = rotate_directory(
            directory=snapshot_cfg["destination"],
            prefix=snapshot_cfg.get("archive_prefix", "snapshot"),
            extension=".tar.gz",
            retention=retention,
            logger=logger,
        )

        result["passed"] = True

        total_deleted = len(result["deleted_files"]) + \
            len(result["deleted_snapshots"])

        if total_deleted > 0:
            log_success(
                logger, f"Rotation complete — {total_deleted} archive(s) removed")
        else:
            log_success(
                logger, "Rotation complete — no old archives to remove")

    except KeyError as e:
        msg = f"Missing config key: {e}"
        log_warning(logger, msg)
        result["error"] = msg

    except Exception as e:
        msg = f"Unexpected error during rotation: {e}"
        log_warning(logger, msg)
        result["error"] = msg

    return result
