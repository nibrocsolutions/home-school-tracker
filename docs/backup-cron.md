# Home School Tracker — scheduled backups
#
# What is best?
#
# 1) Best primary approach: cron ON THE SERVER (Raspberry Pi / Docker host)
#    that writes JSON snapshots to ./backups (and optionally uploads to S3 or
#    Backblaze). This runs even when your Mac is off.
#
# 2) Good secondary approach: Mac cron/curl that pulls /api/backup/export with
#    a shared token and saves files locally. Useful as an extra offsite copy,
#    but unreliable as the only schedule if the Mac sleeps or is away.
#
# Avoid relying only on "the web app pushes to S3 from a browser click."
# Use the CLI (`python -m app.backup_snapshot`) from cron instead — same export
# format as Admin → Export Backup.

## Server-side snapshots (recommended)

1. Mount `./backups` (already in docker-compose.yml) and set optional env vars
   in `.env`:

```bash
BACKUP_DIR=/app/backups
BACKUP_KEEP_COUNT=28
# Optional offsite copy:
# BACKUP_S3_URI=s3://your-bucket/home-school-tracker/
# or a custom command:
# BACKUP_UPLOAD_CMD=rclone copy '{path}' b2:homeschool-backups/
```

2. Run a snapshot manually:

```bash
docker compose exec app python -m app.backup_snapshot
```

3. Install the server crontab example:

```bash
crontab -e
# paste lines from scripts/crontab.server.example (update the project path)
```

Snapshots land in `./backups/hst-backup-YYYYMMDD-HHMMSS.json`.

## Mac pull (optional secondary)

1. Set a long random token on the server:

```bash
# in .env
BACKUP_EXPORT_TOKEN=long-random-secret
```

Restart the app, then:

```bash
curl -fsS -H "Authorization: Bearer long-random-secret" \
  "https://your-host/api/backup/export" \
  -o ~/Documents/hst-backups/hst-backup.json
```

2. See `scripts/crontab.mac.example` and `scripts/mac-backup.env.example`.

## Media files

JSON backups include media *paths/URLs*, not the binary files under `./media`.
Archive `./media` separately (the server crontab example includes a daily tar).

## Restore

Use **Admin → Database Backup → Import Backup**, or keep a known-good
`hst-backup-*.json` ready before risky changes.
