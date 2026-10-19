#!/usr/bin/env bash
# Decrypt a backup made by .github/workflows/backup.yml.
#
# Usage (Git Bash on Windows, or any shell with openssl and gunzip):
#   bash scripts/decrypt-backup.sh partner_backup_<stamp>.json.gz.enc
#
# Asks for the backup password (or reads BACKUP_PASSPHRASE) and writes
# partner_backup_<stamp>.json next to the input. The output holds personal
# data: keep it outside the repository and delete it when done.
set -euo pipefail

input="${1:?usage: bash scripts/decrypt-backup.sh <backup.json.gz.enc>}"
output="${input%.gz.enc}"
[ "$output" != "$input" ] || { echo "Expected a .json.gz.enc file" >&2; exit 1; }
[ ! -e "$output" ] || { echo "$output already exists; not overwriting" >&2; exit 1; }

if [ -z "${BACKUP_PASSPHRASE:-}" ]; then
  read -rsp 'Backup password: ' BACKUP_PASSPHRASE
  echo
fi
export BACKUP_PASSPHRASE

umask 077
if ! openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 \
    -pass env:BACKUP_PASSPHRASE -in "$input" | gunzip > "$output"; then
  rm -f "$output"
  echo "Decryption failed: wrong password or damaged file" >&2
  exit 1
fi
echo "Decrypted to $output"
