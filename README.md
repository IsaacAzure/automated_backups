# backup_tool

A personal system backup tool for Fedora Linux. Runs nightly via anacron and produces timestamped file archives and Btrfs system snapshots, with integrity verification, automatic rotation, external drive transfer, and an emailed HTML report after every run.

Built as a sysadmin portfolio project.

---

## What it does

- Zips configured source directories into timestamped `.zip` archives
- Creates a read-only Btrfs snapshot of the root subvolume and archives it as `.tar.gz`
- Verifies both archives for corruption and file count
- Enforces a 7-day retention policy on both archive types
- Rsyncs both backup directories to an external drive
- Sends an HTML email report summarising every stage — success or failure
- Logs everything to a rotating daily log file (7 days retained)

---

## Stack

| Component    | Tool                          |
|-------------|-------------------------------|
| Language     | Python 3                      |
| Scheduling   | anacron                       |
| File backup  | zipfile (stdlib)              |
| Snapshots    | Btrfs + tarfile (stdlib)      |
| Transfer     | rsync                         |
| Email        | smtplib SMTP/TLS (stdlib)     |
| Config       | YAML (pyyaml)                 |
| Logging      | logging.TimedRotatingFileHandler |

---

## Project structure

```
backup_tool/
├── backup.py               # Master orchestrator — entry point
├── config.yaml             # All configuration — edit this before running
├── logger.py               # Centralised logging shared across all modules
├── requirements.txt        # pyyaml only
│
├── modules/
│   ├── file_backup.py      # Zips source dirs → timestamped .zip
│   ├── snapshot.py         # Btrfs snapshot → .tar.gz
│   ├── verify.py           # Integrity checks on both archives
│   ├── rotate.py           # 7-day retention policy
│   ├── transfer.py         # rsync to external drive
│   └── notify.py           # HTML email report
│
├── backups/
│   ├── files/              # File backup archives (auto-created)
│   └── snapshots/          # Snapshot archives (auto-created)
│
├── logs/
│   └── backup.log          # Rotates daily, 7 days retained (auto-created)
│
└── cron/
    └── backup_tool         # anacron entry — install to /etc/cron.daily/
```

---

## Prerequisites

- Fedora Linux with Btrfs root filesystem (default since Fedora 33)
- Python 3.9+
- rsync installed (`sudo dnf install rsync`)
- Root access (required for Btrfs snapshot commands)
- A Gmail account with 2FA enabled for email reports

### Confirm Btrfs is your filesystem

```bash
findmnt -T / -o FSTYPE
# Expected output: btrfs

sudo btrfs subvolume list /
# Should show your subvolumes including root and home
```

---

## Installation

### 1. Clone the project

```bash
git clone https://github.com/youruser/backup_tool.git
sudo mv backup_tool /opt/backup_tool
```

### 2. Install dependencies

```bash
cd /opt/backup_tool
pip3 install -r requirements.txt
```

### 3. Create the snapshot directory

```bash
sudo mkdir -p /.snapshots
```

### 4. Configure the tool

```bash
sudo nano /opt/backup_tool/config.yaml
```

See the Configuration section below for what to fill in.

### 5. Install the anacron job

```bash
sudo cp /opt/backup_tool/cron/backup_tool /etc/cron.daily/backup_tool
sudo chmod +x /etc/cron.daily/backup_tool
```

### 6. Run manually to test

```bash
sudo python3 /opt/backup_tool/backup.py
```

Check the output and verify an email report arrives before relying on the automated schedule.

---

## Configuration

All settings live in `config.yaml`. Nothing is hardcoded in the scripts.

### File backup sources

```yaml
file_backup:
  sources:
    - /home/solo/documents
    - /home/solo/projects
    - /etc
  destination: /var/backups/backup_tool/files
  archive_prefix: backup
```

Add or remove paths under `sources`. Each path is zipped recursively.

### Btrfs snapshot

```yaml
snapshot:
  enabled: true
  btrfs:
    subvolume: /
    snapshot_dir: /.snapshots
    snapshot_name: backup_snap
  destination: /var/backups/backup_tool/snapshots
  archive_prefix: snapshot
```

`subvolume: /` snapshots the root subvolume. To find your subvolumes:

```bash
sudo btrfs subvolume list /
```

**Note:** `/home` is a separate Btrfs subvolume and is intentionally excluded from the snapshot. Personal data under `/home` is covered by `file_backup` sources. To include `/home` in snapshots, add it as a second subvolume.

### Retention

```yaml
retention:
  days: 7
```

Archives older than 7 days are deleted from both `files/` and `snapshots/`. Log files rotate on the same schedule.

### External drive

```yaml
transfer:
  enabled: true
  drive_mount_path: /run/media/solo/Backup
```

Fedora auto-mounts drives at `/run/media/<username>/<drive_label>`. If the drive is not mounted when the job runs, transfer is skipped with a warning — the job does not fail.

### Email

```yaml
email:
  enabled: true
  smtp_host: smtp.gmail.com
  smtp_port: 587
  use_tls: true
  sender: your_email@gmail.com
  password: your_app_password_here
  subject: "Backup Report — {status} {date}"
  recipients:
    - admin@yourdomain.com
```

Gmail requires an **App Password** — your regular Gmail password will not work.

**Generating a Gmail App Password:**

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Security → 2-Step Verification (must be enabled first)
3. Security → App Passwords
4. Generate one named `backup_tool`
5. Paste the 16-character password into `config.yaml`

---

## How anacron handles missed runs

Unlike cron, anacron tracks when jobs last ran and catches up on missed runs the next time the device boots. This makes it the correct choice for a personal device that is not always powered on at the scheduled time.

The script in `/etc/cron.daily/` is picked up by anacron automatically — no additional configuration is required.

---

## Verifying it is working

After the first run, check the following:

```bash
# Check log output
sudo tail -50 /var/log/backup_tool/backup.log

# List created archives
ls -lh /var/backups/backup_tool/files/
ls -lh /var/backups/backup_tool/snapshots/

# Check anacron recorded the run
sudo ls /var/spool/anacron/
```

An email report should also arrive in your configured inbox.

---

## Troubleshooting

**Btrfs snapshot fails with permission error**
The script must run as root. Confirm the anacron entry runs as root or prefix with `sudo` when testing manually.

**Email not sending**
Confirm 2FA is enabled on the Gmail account and that an App Password (not your regular password) is in `config.yaml`. Test SMTP connectivity: `telnet smtp.gmail.com 587`

**Drive not being synced**
Run `lsblk` to confirm the drive is mounted. The mount path must match `drive_mount_path` in config exactly. Transfer is skipped silently if the drive is absent — check `backup.log` for the warning.

**Archives not being rotated**
Confirm `retention.days` is set in `config.yaml` and that the archive filenames match the configured prefix. Rotation only targets files matching `{prefix}_*.zip` and `{prefix}_*.tar.gz`.

---

## Log output example

```
2025-01-15 02:00:00  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:00  INFO       Backup Job Starting
2025-01-15 02:00:00  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:00  INFO     Config loaded successfully
2025-01-15 02:00:00  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:00  INFO       File Backup
2025-01-15 02:00:00  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:01  INFO     ✓  Archive created — 142 files, 2.3 MB
2025-01-15 02:00:01  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:01  INFO       System Snapshot (Btrfs)
2025-01-15 02:00:01  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:04  INFO     ✓  Btrfs snapshot created
2025-01-15 02:00:09  INFO     ✓  Snapshot archived — 4.7 GB
2025-01-15 02:00:09  INFO     ✓  Raw snapshot removed: /.snapshots/backup_snap
2025-01-15 02:00:09  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:09  INFO       Integrity Verification
2025-01-15 02:00:09  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:10  INFO     ✓  Zip verified — 142 files, 2.3 MB
2025-01-15 02:00:11  INFO     ✓  Tar verified — 4.7 GB
2025-01-15 02:00:11  INFO     ✓  All integrity checks passed
2025-01-15 02:00:11  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:11  INFO       Rotation Policy
2025-01-15 02:00:11  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:11  INFO     ✓  Rotation complete — 1 archive(s) removed
2025-01-15 02:00:11  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:11  INFO       External Drive Transfer
2025-01-15 02:00:11  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:14  INFO     ✓  Transfer complete — /run/media/solo/Backup
2025-01-15 02:00:14  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:14  INFO       Email Report
2025-01-15 02:00:14  INFO     ───────────────────────────────────────────────────────
2025-01-15 02:00:15  INFO     ✓  Report sent — Backup Report — SUCCESS 2025-01-15
2025-01-15 02:00:15  INFO     ═══════════════════════════════════════════════════════
```
