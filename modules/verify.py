"""
verify.py — Backup Integrity Verification Module

Verifies the integrity of archives produced by file_backup.py and snapshot.py.

Checks performed:
    - Archive is not corrupt (zipfile.testzip / tarfile check)
    - File count inside archive matches what was zipped
    - Archive size is recorded and returned for the email report

Called by backup.py after both backup stages complete.
Results are passed to notify.py for inclusion in the email report.
"""

import zipfile
import tarfile
from pathlib import Path

from logger import get_logger, log_section, log_success, log_failure, log_warning


# ---------------------------
# Helpers
# ---------------------------

def format_bytes(size: int) -> str:
    """Convert a byte count into a human readable string e.g. 2.3 MB."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


# ---------------------------
# Verify ZIP — used for file_backup archives
# ---------------------------

def verify_zip(archive_path: str, expected_files: int, logger) -> dict:
    """
    Verify a .zip archive produced by file_backup.py.

    Args:
        archive_path   : Absolute path to the .zip file
        expected_files : Number of files added during zipping (from file_backup result)
        logger         : Shared logger instance

    Returns:
        result dict — {
            passed         : bool  — True if all checks passed
            archive        : str   — archive filename only (not full path)
            size_human     : str   — human readable archive size
            expected_files : int   — files counted during backup
            actual_files   : int   — files counted inside the archive
            errors         : list  — list of error strings, empty if passed
        }
    """
    path = Path(archive_path)

    result = {
        "passed": False,
        "archive": path.name,
        "size_human": "0 B",
        "expected_files": expected_files,
        "actual_files": 0,
        "errors": [],
    }

    logger.info(f"Verifying zip : {path.name}")

    # --- Check archive exists ----------------------
    if not path.exists():
        msg = f"Archive not found: {archive_path}"
        log_failure(logger, msg)
        result["errors"].append(msg)
        return result

    try:
        with zipfile.ZipFile(path, "r") as zf:

            # --- Corruption check -------------------
            # testzip() reads every entry and returns the name
            # of the first bad entry, or None if all are clean
            bad_file = zf.testzip()
            if bad_file:
                msg = f"Corrupted entry found: {bad_file}"
                log_failure(logger, msg)
                result["errors"].append(msg)
                return result

            # --- File count check -------------------
            # Filter out directory entries — count files only
            actual_files = len([
                name for name in zf.namelist()
                if not name.endswith("/")
            ])
            result["actual_files"] = actual_files

            if actual_files != expected_files:
                msg = (
                    f"File count mismatch — "
                    f"expected {expected_files}, found {actual_files}"
                )
                log_warning(logger, msg)
                result["errors"].append(msg)
                # Not a hard failure — archive may still be usable
                # but worth flagging in the email report

        # --- Size -----------------------------------
        size_human = format_bytes(path.stat().st_size)
        result["size_human"] = size_human

        # Passed if no errors were recorded
        if not result["errors"]:
            result["passed"] = True
            log_success(
                logger, f"Zip verified — {actual_files} files, {size_human}")

    except zipfile.BadZipFile as e:
        msg = f"Bad zip file: {e}"
        log_failure(logger, msg)
        result["errors"].append(msg)

    except OSError as e:
        msg = f"File system error: {e}"
        log_failure(logger, msg)
        result["errors"].append(msg)

    except Exception as e:
        msg = f"Unexpected error: {e}"
        log_failure(logger, msg)
        result["errors"].append(msg)

    return result


# ---------------------------
# Verify TAR.GZ — used for snapshot archives
# ---------------------------
def verify_tar(archive_path: str, logger) -> dict:
    """
    Verify a .tar.gz archive produced by snapshot.py.

    Note: expected_files is not checked for tar archives — the snapshot
    captures the entire Btrfs subvolume so there is no pre-counted file
    total to compare against. Corruption check and size are verified instead.

    Args:
        archive_path : Absolute path to the .tar.gz file
        logger       : Shared logger instance

    Returns:
        result dict — {
            passed     : bool  — True if all checks passed
            archive    : str   — archive filename only
            size_human : str   — human readable archive size
            errors     : list  — list of error strings, empty if passed
        }
    """
    path = Path(archive_path)

    result = {
        "passed": False,
        "archive": path.name,
        "size_human": "0 B",
        "errors": [],
    }

    logger.info(f"Verifying tar : {path.name}")

    # --- Check archive exists ----------------------
    if not path.exists():
        msg = f"Archive not found: {archive_path}"
        log_failure(logger, msg)
        result["errors"].append(msg)
        return result

    try:
        # --- Corruption check -------------------
        # Opens the tar and attempts to read every member
        # Raises TarError if the archive is corrupt
        with tarfile.open(path, "r:gz") as tf:
            members = tf.getmembers()
            file_count = len([m for m in members if m.isfile()])

        # --- Size -----------------------------------
        size_human = format_bytes(path.stat().st_size)
        result["size_human"] = size_human

        result["passed"] = True
        log_success(logger, f"Tar verified — {file_count} files, {size_human}")

    except tarfile.TarError as e:
        msg = f"Corrupt tar archive: {e}"
        log_failure(logger, msg)
        result["errors"].append(msg)

    except OSError as e:
        msg = f"File system error: {e}"
        log_failure(logger, msg)
        result["errors"].append(msg)

    except Exception as e:
        msg = f"Unexpected error: {e}"
        log_failure(logger, msg)
        result["errors"].append(msg)

    return result


# ---------------------------
# Core — called by backup.py
# ---------------------------

def run(cfg: dict, file_backup_result: dict, snapshot_result: dict) -> dict:
    """
    Run integrity checks on both archives.

    Args:
        cfg                 : Full config dict from config.yaml
        file_backup_result  : Result dict returned by file_backup.run()
        snapshot_result     : Result dict returned by snapshot.run()

    Returns:
        result dict — {
            passed       : bool  — True if both archives passed
            zip_result   : dict  — verify_zip() result
            tar_result   : dict  — verify_tar() result
        }
    """
    log_path = cfg.get("logging", {}).get(
        "log_file", "/var/log/backup_tool/backup.log")
    logger = get_logger(log_path)

    log_section(logger, "Integrity Verification")

    zip_result = {"passed": False, "errors": ["File backup did not complete."]}
    tar_result = {"passed": False, "errors": ["Snapshot did not complete."]}

    # --- Verify zip -----------------------------------
    if file_backup_result.get("passed") and file_backup_result.get("archive_path"):
        zip_result = verify_zip(
            archive_path=file_backup_result["archive_path"],
            expected_files=file_backup_result["total_files"],
            logger=logger,
        )
    else:
        log_warning(
            logger, "Skipping zip verification — file backup did not produce an archive")

    # --- Verify tar -------------------------------------
    if snapshot_result.get("passed") and snapshot_result.get("archive_path"):
        tar_result = verify_tar(
            archive_path=snapshot_result["archive_path"],
            logger=logger,
        )
    else:
        log_warning(
            logger, "Skipping tar verification — snapshot did not produce an archive")

    overall_passed = zip_result["passed"] and tar_result["passed"]

    if overall_passed:
        log_success(logger, "All integrity checks passed")
    else:
        log_failure(logger, "One or more integrity checks failed — see above")

    return {
        "passed": overall_passed,
        "zip_result": zip_result,
        "tar_result": tar_result,
    }
