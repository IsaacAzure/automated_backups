"""
notify.py — Email Notification Module

Builds a unified HTML email report from the results of all pipeline stages
and sends it via Gmail SMTP with TLS.

The report covers:
    - File backup result (archive name, size, file count)
    - Snapshot result (archive name, size)
    - Integrity verification (pass/fail for both archives)
    - Rotation summary (archives deleted, retention policy)
    - Transfer status (synced or skipped)
    - Any errors recorded across all stages

Subject line format:
    "Backup Report — SUCCESS 2025-01-15"
    "Backup Report — FAILURE 2025-01-15"

Called by backup.py as the final stage of the pipeline.
Sends even if earlier stages failed — failure reports are the most important ones.
"""

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from logger import get_logger, log_section, log_success, log_failure


# ---------------------------
# Helpers
# ---------------------------


def _status_badge(passed: bool) -> str:
    """Return a coloured HTML badge for pass/fail status."""
    if passed:
        return '<span style="color:#2ecc71;font-weight:bold;">PASSED ✓</span>'
    return '<span style="color:#e74c3c;font-weight:bold;">FAILED ✗</span>'


def _error_list(errors: list) -> str:
    """Return an HTML list of errors, or a green none if empty."""
    if not errors:
        return '<li style="color:#2ecc71;">None</li>'
    return "".join(f'<li style="color:#e74c3c;">{e}</li>' for e in errors)


def _deleted_list(deleted: list) -> str:
    """Return an HTML list of deleted archives, or none if empty."""
    if not deleted:
        return "<li>None — no archives exceeded retention period</li>"
    return "".join(f"<li>{d}</li>" for d in deleted)


# ---------------------------
# HTML Report Builder
# ---------------------------

def build_report(
    overall_passed: bool,
    file_result: dict,
    snapshot_result: dict,
    verify_result: dict,
    rotate_result: dict,
    transfer_result: dict,
) -> str:
    """
    Build the full HTML email report body.

    Args:
        overall_passed   : True if every pipeline stage passed
        file_result      : Result dict from file_backup.run()
        snapshot_result  : Result dict from snapshot.run()
        verify_result    : Result dict from verify.run()
        rotate_result    : Result dict from rotate.run()
        transfer_result  : Result dict from transfer.run()

    Returns:
        HTML string ready to attach to a MIMEMultipart email
    """
    now = datetime.now().strftime("%A %d %B %Y, %H:%M:%S")
    status_colour = "#2ecc71" if overall_passed else "#e74c3c"
    status_label = "SUCCESS" if overall_passed else "FAILURE"

    # --- Collect all errors across stages ----------------
    all_errors = []
    for result in [file_result, snapshot_result, rotate_result, transfer_result]:
        if result.get("error"):
            all_errors.append(result["error"])
    for errors in [
        verify_result.get("zip_result", {}).get("errors", []),
        verify_result.get("tar_result", {}).get("errors", []),
    ]:
        all_errors.extend(errors)

    # --- Rotation summary -------------------------------
    deleted_files = rotate_result.get("deleted_files", [])
    deleted_snapshots = rotate_result.get("deleted_snapshots", [])
    retention_days = rotate_result.get("retention_days", 7)

    # --- Transfer summary -------------------------------
    transfer_status = transfer_result.get("status", "Unknown")
    transfer_path = transfer_result.get("drive_path", "N/A")

    # --- Verify results -----------------------------
    zip_result = verify_result.get("zip_result", {})
    tar_result = verify_result.get("tar_result", {})

    html = f"""
    <html>
    <body style="font-family:monospace;background:#0d1117;color:#c9d1d9;padding:32px;margin:0;">

      <!-- Header -->
      <h2 style="color:{status_colour};margin-bottom:4px;">
        Backup Report — {status_label}
      </h2>
      <p style="color:#8b949e;margin-top:0;">{now}</p>
      <hr style="border:none;border-top:1px solid #30363d;margin:24px 0;">

      <!-- File Backup -->
      <h3 style="color:#58a6ff;">File Backup</h3>
      <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
        <tr>
          <td style="padding:4px 16px 4px 0;color:#8b949e;width:160px;">Archive</td>
          <td>{_archive_name(file_result.get("archive_path"))}</td>
        </tr>
        <tr>
          <td style="padding:4px 16px 4px 0;color:#8b949e;">Size</td>
          <td>{file_result.get("size_human", "N/A")}</td>
        </tr>
        <tr>
          <td style="padding:4px 16px 4px 0;color:#8b949e;">Files Zipped</td>
          <td>{file_result.get("total_files", 0)}</td>
        </tr>
        <tr>
          <td style="padding:4px 16px 4px 0;color:#8b949e;">Skipped Sources</td>
          <td>{", ".join(file_result.get("skipped_files", [])) or "None"}</td>
        </tr>
        <tr>
          <td style="padding:4px 16px 4px 0;color:#8b949e;">Status</td>
          <td>{_status_badge(file_result.get("passed", False))}</td>
        </tr>
      </table>
      <hr style="border:none;border-top:1px solid #30363d;margin:24px 0;">

      <!-- System Snapshot -->
      <h3 style="color:#58a6ff;">System Snapshot</h3>
      <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
        <tr>
          <td style="padding:4px 16px 4px 0;color:#8b949e;width:160px;">Archive</td>
          <td>{_archive_name(snapshot_result.get("archive_path"))}</td>
        </tr>
        <tr>
          <td style="padding:4px 16px 4px 0;color:#8b949e;">Size</td>
          <td>{snapshot_result.get("size_human", "N/A")}</td>
        </tr>
        <tr>
          <td style="padding:4px 16px 4px 0;color:#8b949e;">Status</td>
          <td>{_status_badge(snapshot_result.get("passed", False))}</td>
        </tr>
      </table>
      <hr style="border:none;border-top:1px solid #30363d;margin:24px 0;">

      <!-- Integrity Verification -->
      <h3 style="color:#58a6ff;">Integrity Verification</h3>
      <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
        <tr>
          <td style="padding:4px 16px 4px 0;color:#8b949e;width:160px;">Zip Archive</td>
          <td>
            {_status_badge(zip_result.get("passed", False))}
            &nbsp;{zip_result.get("actual_files", 0)} / {zip_result.get("expected_files", 0)} files
            &nbsp;{zip_result.get("size_human", "")}
          </td>
        </tr>
        <tr>
          <td style="padding:4px 16px 4px 0;color:#8b949e;">Tar Archive</td>
          <td>
            {_status_badge(tar_result.get("passed", False))}
            &nbsp;{tar_result.get("size_human", "")}
          </td>
        </tr>
      </table>
      <hr style="border:none;border-top:1px solid #30363d;margin:24px 0;">

      <!-- Rotation -->
      <h3 style="color:#58a6ff;">Rotation — {retention_days} Day Policy</h3>
      <p style="color:#8b949e;margin:4px 0;">File backups removed:</p>
      <ul style="margin:4px 0 12px 0;">{_deleted_list(deleted_files)}</ul>
      <p style="color:#8b949e;margin:4px 0;">Snapshots removed:</p>
      <ul style="margin:4px 0 12px 0;">{_deleted_list(deleted_snapshots)}</ul>
      <hr style="border:none;border-top:1px solid #30363d;margin:24px 0;">

      <!-- Transfer -->
      <h3 style="color:#58a6ff;">External Drive Transfer</h3>
      <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
        <tr>
          <td style="padding:4px 16px 4px 0;color:#8b949e;width:160px;">Drive Path</td>
          <td>{transfer_path}</td>
        </tr>
        <tr>
          <td style="padding:4px 16px 4px 0;color:#8b949e;">Status</td>
          <td>{transfer_status}</td>
        </tr>
      </table>
      <hr style="border:none;border-top:1px solid #30363d;margin:24px 0;">

      <!-- Errors -->
      <h3 style="color:#58a6ff;">Errors</h3>
      <ul style="margin:4px 0 12px 0;">{_error_list(all_errors)}</ul>

      <!-- Footer -->
      <hr style="border:none;border-top:1px solid #30363d;margin:24px 0;">
      <p style="color:#8b949e;font-size:11px;margin:0;">
        Generated by backup_tool &nbsp;|&nbsp; {now}
      </p>

    </body>
    </html>
    """
    return html


def _archive_name(path: str | None) -> str:
    """Extract filename from a full path, or return N/A if None."""
    if not path:
        return "N/A — archive was not created"
    from pathlib import Path
    return Path(path).name


# ---------------------------
# Core — called by backup.py
# ---------------------------

def run(
    cfg: dict,
    file_result: dict,
    snapshot_result: dict,
    verify_result: dict,
    rotate_result: dict,
    transfer_result: dict,
) -> None:
    """
    Build the HTML report and send it via Gmail SMTP.

    Args:
        cfg              : Full config dict from config.yaml
        file_result      : Result dict from file_backup.run()
        snapshot_result  : Result dict from snapshot.run()
        verify_result    : Result dict from verify.run()
        rotate_result    : Result dict from rotate.run()
        transfer_result  : Result dict from transfer.run()
    """
    log_path = cfg.get("logging", {}).get(
        "log_file", "/var/log/backup_tool/backup.log")
    logger = get_logger(log_path)

    log_section(logger, "Email Report")

    email_cfg = cfg.get("email", {})

    if not email_cfg.get("enabled", False):
        logger.info("Email reporting is disabled in config — skipping")
        return

    # --- Determine overall status -----------------------
    overall_passed = all([
        file_result.get("passed",     False),
        snapshot_result.get("passed", False),
        verify_result.get("passed",   False),
        rotate_result.get("passed",   False),
    ])
    # Transfer is not included in overall_passed —
    # a missing drive is a warning, not a failure

    # --- Build subject line -----------------------------
    status = "SUCCESS" if overall_passed else "FAILURE"
    date = datetime.now().strftime("%Y-%m-%d")

    subject_template = email_cfg.get(
        "subject", "Backup Report — {status} {date}")
    subject = subject_template.format(status=status, date=date)

    # --- Build HTML report -----------------------------
    html = build_report(
        overall_passed=overall_passed,
        file_result=file_result,
        snapshot_result=snapshot_result,
        verify_result=verify_result,
        rotate_result=rotate_result,
        transfer_result=transfer_result,
    )

    # --- Compose email --------------------------------
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_cfg["sender"]
    msg["To"] = ", ".join(email_cfg["recipients"])
    msg.attach(MIMEText(html, "html"))

    # --- Send via SMTP -----------------------------
    try:
        with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"]) as server:
            if email_cfg.get("use_tls", True):
                server.starttls()
            server.login(email_cfg["sender"], email_cfg["password"])
            server.sendmail(
                email_cfg["sender"],
                email_cfg["recipients"],
                msg.as_string(),
            )

        log_success(logger, f"Report sent — {subject}")
        log_success(
            logger, f"Recipients  — {', '.join(email_cfg['recipients'])}")

    except smtplib.SMTPAuthenticationError:
        log_failure(
            logger, "SMTP authentication failed — check sender and App Password in config")

    except smtplib.SMTPConnectError:
        log_failure(
            logger, f"Could not connect to {email_cfg['smtp_host']}:{email_cfg['smtp_port']}")

    except smtplib.SMTPException as e:
        log_failure(logger, f"SMTP error: {e}")

    except Exception as e:
        log_failure(logger, f"Unexpected error sending email: {e}")
