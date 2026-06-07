"""
File Backup Module

Reads source directories from config.yaml, zips them into a timestamped archive, 
then saves it to the configured destination directory.

Called by backup.py as the first stage of the backup pipeline.

Output example:
    /var/
    /var/backups/file-backups/backups_2026-05-12_02-00-00.zip
"""

import zipfile
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
            return f"{size:.2f}{unit}"
        size /= 1024
    return f"{size:.2f} PB"

# ---------------------------
# Core Function
# ---------------------------


def run(cfg: dict) -> dict:
    """
    Execute the file backup stage.

    Reads source path and destination from config, zips all files into a
    timestamped archive, and returns a result dict for use by verify.py and notify.py

    Args:
        cfg: Full config loaded from config.yaml by backup.py

    Returns:
    result - dict - {
        passed          : bool  - True if archive backup was successfully created
        archive_path    : str   - Absolute path to the created archive
        total_files     : int   - Number of files added to the archive
        skipped_files   : list  - source paths that were missiing
        size_human      : str   - Human readable size of the archive 
        error           : str   - error message if the job failed, else None. 
        }
    """

    log_path = cfg.get("logging", {}).get(
        "log_file", "/var/log/backup_tool/backup.log")
    logger = get_logger(log_path)

    log_section(logger, "File Backup")

    result = {
        "passed": False,
        "archive_path": None,
        "total_files": 0,
        "skipped_files": [],
        "size_human": None,
        "error": None,
    }

    try:
        backup_cfg = cfg["file_backup"]
        sources = backup_cfg["sources"]
        dest_dir = backup_cfg["destination"]
        prefix = backup_cfg.get("archive_prefix", "backup")

        # ---Build archive path------------------------
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archive_name = f"{prefix}_{timestamp}.zip"
        archive_path = Path(dest_dir) / archive_name

        # Create destination directory if it doesn't exist
        Path(dest_dir).mkdir(parents=True, exist_ok=True)

        logger.info(f"Sources      : {sources}")
        logger.info(f"Destination  : {dest_dir}")
        logger.info(f"Archive      : {archive_name}")

        # ---Zip sources-----------------
        total_files = 0

        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for source in sources:
                source_path = Path(source)

                # skip missing paths - log warning but continue
                if not source_path.exists():
                    log_warning(
                        logger, f"Source not found, skipping: {source}")
                    result["skipped_files"].append(source)
                    continue

                # Single File
                if source_path.is_file():
                    zf.write(source_path, source_path.name)
                    total_files += 1
                    logger.debug(f" Added file: {source_path}")

                else:
                    for file_path in source_path.rglob('*'):
                        if file_path.is_file():
                            # Preserve the dir structure inside the zip
                            arcname = file_path.relative_to(source_path.parent)
                            zf.write(file_path, arcname)
                            total_files += 1
                            logger.debug(f" Added  : {file_path}")

        # ---Record Results-----------------
        size_bytes = archive_path.stat().st_size
        size_human = format_bytes(size_bytes)

        result["passed"] = True
        result["archive_path"] = str(archive_path)
        result["total_files"] = total_files
        result["size_human"] = size_human

        log_success(
            logger, f"Archive created - {total_files} files, (size: {size_human})")
        if result["skipped_files"]:
            log_warning(
                logger, f"{len(result['skipped_files'])} source(s) skipped - see above")

    except KeyError as e:
        msg = f"Missing config key: {e}"
        log_failure(logger, msg)
        result["error"] = msg

    except OSError as e:
        msg = f"File system error: {e}"
        log_failure(logger, msg)
        result["error"] = msg

    except Exception as e:
        msg = f"Unexpected error: {e}"
        log_failure(logger, msg)
        result["error"] = msg

    return result
