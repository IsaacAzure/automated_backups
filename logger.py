"""
logger.py — Centralised logging for backup_tool

Every module imports get_logger() from here.
Writes to both a log file (DEBUG+) and stdout (INFO+).
The log file path is read from config.yaml.
"""

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def get_logger(log_path: str = "/var/log/backup_tool/backup_tool.log"
               ) -> logging.Logger:
    """
    Build and return the shared 'backup' logger.

    Calling this multiple times is safe — handlers are only added once.

    Args:
        log_path: Absolute path to the log file.
                  Passed in from config.yaml by backup.py.

    Returns:
        Configured logging.Logger instance.
    """

    logger = logging.getLogger("backup")

    # Defined the sole logger required.
    # Avoid duplicate handlers if get_logger() is called multiple times
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    _fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
# (levelname)8s pads the log level to 8 characters. For a more uniformed output.

# ---------------------------
# File Handler
# Captures all levels from DEBUG to CRITICAL
# ---------------------------

    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)

        fh = TimedRotatingFileHandler(
            log_path,
            when="midnight",  # Rotate at midnight daily
            backupCount=7,  # Keep 7 days of logs, delete older files
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(_fmt)
        logger.addHandler(fh)

    except OSError as e:
        # If the log file can't be created, print to warning to stdout and continue.
        # Job will run, with out the file logging.
        print(f"[logger] WARNING: Could not create log file at {log_path}: {e}",
              file=sys.stderr,
              )

# ---------------------------
# Console Handler
# Captures all levels from INFO to CRITICAL
# Debug written to log file only.
# ---------------------------

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(_fmt)
    logger.addHandler(ch)

    return logger

# ---------------------------
# Convenience Helpers
# ---------------------------


def log_section(logger: logging.Logger, title: str) -> None:
    """Print a visible section divider - seperates pipleline stages in the log."""
    logger.info('-' * 55)
    logger.info(f' {title}')
    logger.info('-' * 55)


def log_success(logger: logging.Logger, message: str) -> None:
    logger.info(f"✓  {message}")


def log_failure(logger: logging.Logger, message: str) -> None:
    logger.error(f"✗  {message}")


def log_warning(logger: logging.Logger, message: str) -> None:
    logger.warning(f"⚠  {message}")
