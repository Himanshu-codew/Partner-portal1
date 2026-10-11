# Backup and Restore Guide

This project includes `core/management/commands/backup_data.py` to create a portable JSON backup of the database. Backups contain personal data and password hashes — **store them outside the repository and encrypted/private**.

## Taking a backup (local, against Neon from Windows PowerShell)

For a one-off session, set `DATABASE_URL` only for that PowerShell process (do **not** export globally). Replace the placeholder with your Neon connection string.

```powershell
# Set DATABASE_URL for this session only
$env:DATABASE_URL = "postgresql://user:password@your-neon-host.neon.tech/dbname?sslmode=require"

# Run backup command
python manage.py backup_data --output backups/partner_backup_$(Get-Date -Format "yyyyMMddTHHmmssZ").json
# Or let command choose default: backups/partner_backup_<UTC timestamp>.json
```

Notes (verified):
- The command refuses to overwrite an existing file.
- It prints the record count and file size; **it never prints the database URL**.
- It uses `dumpdata --all --natural-foreign --natural-primary` and excludes `contenttypes`, `auth.permission`, `admin.logentry`, `sessions`.

## Taking a backup from Render (cron job)

You can run `python manage.py backup_data --output /tmp/partner_backup_YYYYMMDDTHHMMSSZ.json` in a cron job and upload it to an external storage (S3/Cloudinary/private bucket). The app's file system is ephemeral on free Render — do **not** store backups inside the app filesystem long-term.

## Restoring into an empty database

Restoring is a destructive operation for the target database. Only restore into an **empty** database (no tables/data).

1. Set target database (session-only, Windows PowerShell):
   ```powershell
   $env:DATABASE_URL = "postgresql://user:password@your-target-host/dbname?sslmode=require"
   ```

2. Run migrations to create schema:
   ```powershell
   python manage.py migrate
   ```

3. Load the backup JSON:
   ```powershell
   python manage.py loaddata path\to\backup.json
   ```

## Verify after restore

- Check record counts (sample groups): users, partner profiles, leads, orders, tickets, announcements, documents, KYC documents, notification logs.
- Log in as an existing user/staff and spot-check key pages (dashboard, leads, tickets, recycle bin).
- Run `python manage.py check` (no issues).

## Frequency and retention

- **Frequency:** verify recommended cadence (e.g. daily) based on how often data changes; mark "verify" if policy not specified.
- **Retention:** keep multiple generations (rolling) and test a restore at least quarterly.
- **Storage:** outside the repo, encrypted at rest, access restricted to owner.

## Warnings

- Backups contain **personal data** and **password hashes**. Treat as sensitive.
- Do not commit backups to git (repo `.gitignore` excludes `backups/`, `*.backup.json`, `backup_*.json`, `*.json.bak`).
- After taking a backup, remove/clear `$env:DATABASE_URL` from the session if sharing the shell.
- Never print/log the database URL in any output. The command abides by this rule.

## Troubleshooting

### `CommandError: Unable to serialize database: cursor "_django_curs_..." does not exist`

Cause: Django's `dumpdata` reads rows with `queryset.iterator()`, which uses a
**server-side (named) cursor** on Postgres. Neon may drop that cursor — for
example after the compute auto-suspends, or when the connection goes through a
connection pooler (PgBouncer) that does not keep named cursors alive for the
whole dump.

What `backup_data` does now:
- Before serialising it sets `DISABLE_SERVER_SIDE_CURSORS = True` on the
  connection, closes the connection so the change takes effect, and restores the
  original value afterwards (in a `finally` block).
- If the dump still fails it deletes the partial output file and prints a short
  error — it never prints the database URL.

If you still hit it (for example other commands or long-running queries):

1. Enable client-side cursors globally for the app by setting the environment
   variable on Render and redeploying:
   ```
   DB_DISABLE_SERVER_SIDE_CURSORS=True
   ```
   (also documented in `.env.example` and `docs/RUNBOOK.md`).
2. Prefer the Neon **direct** (non-pooled) connection string for large dumps
   when available.
3. Re-run the backup. A failed run leaves no partial file; a successful run
   writes valid JSON and prints the record count and size.

## Troubleshooting quick reference

| Symptom | Cause | Fix |
|---|---|---|
| `cursor "_django_curs_..." does not exist` | Neon dropped a server-side cursor (suspend/pooler). | `backup_data` disables them automatically; set `DB_DISABLE_SERVER_SIDE_CURSORS=True` globally if needed. |
| CommandError "already exists" | Output path already has a file. | Choose a new `--output`; the command refuses to overwrite. |
| JSON count read fails | Output truncated / not valid JSON. | Re-run; partial file is removed automatically on failure. |
