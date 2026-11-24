#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
: "${DATABASE_URL:?Set DATABASE_URL to the backup source database}"
: "${PGPASSFILE:?Set PGPASSFILE to a protected PostgreSQL password file}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
if [[ "$DATABASE_URL" == *"://"* && "$DATABASE_URL" == *"://*:*@"* ]]; then
  echo "Refusing DATABASE_URL containing an inline password; use PGPASSFILE." >&2; exit 2
fi
if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || (( RETENTION_DAYS < 1 || RETENTION_DAYS > 3650 )); then
  echo "BACKUP_RETENTION_DAYS must be an integer from 1 to 3650." >&2; exit 2
fi
command -v pg_dump >/dev/null || { echo "pg_dump is required." >&2; exit 127; }
command -v pg_restore >/dev/null || { echo "pg_restore is required to validate the archive." >&2; exit 127; }
command -v sha256sum >/dev/null || { echo "sha256sum is required." >&2; exit 127; }
[[ -f "$PGPASSFILE" ]] || { echo "PGPASSFILE does not exist." >&2; exit 2; }
chmod 600 "$PGPASSFILE"
mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
final="$BACKUP_DIR/medipredict-$stamp.dump"; tmp="$final.partial"
trap 'rm -f "$tmp"' EXIT
pg_dump --no-password --format=custom --compress=6 --file="$tmp" "$DATABASE_URL"
test -s "$tmp"
pg_restore --list "$tmp" >/dev/null
mv "$tmp" "$final"
(cd "$BACKUP_DIR" && sha256sum "$(basename "$final")" > "$(basename "$final").sha256")
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'medipredict-*.dump' -mtime "+$RETENTION_DAYS" -print -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'medipredict-*.dump.sha256' -mtime "+$RETENTION_DAYS" -delete
printf 'Backup created: %s\n' "$final"
