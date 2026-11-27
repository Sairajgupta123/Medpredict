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

# Serialize backups and prevent same-second runs from overwriting a prior archive.
lock="$BACKUP_DIR/.medipredict-backup.lock"
if ! mkdir "$lock" 2>/dev/null; then
  echo "Another backup may be running (lock exists: $lock)." >&2; exit 2
fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
final="$BACKUP_DIR/medipredict-$stamp.dump"
tmp="$final.partial"
checksum_tmp="$final.sha256.partial"
published=0
cleanup() {
  rm -f "$tmp" "$checksum_tmp"
  if [[ "$published" != "1" ]]; then rm -f "$final" "$final.sha256"; fi
  rmdir "$lock" 2>/dev/null || true
}
trap cleanup EXIT
if [[ -e "$final" || -e "$final.sha256" ]]; then
  echo "A backup for this timestamp already exists; refusing to overwrite it." >&2; exit 2
fi

pg_dump --no-password --format=custom --compress=6 --file="$tmp" "$DATABASE_URL"
test -s "$tmp"
pg_restore --list "$tmp" >/dev/null
# Prepare the checksum against the final archive name before publishing either file.
(cd "$BACKUP_DIR" && sha256sum "$(basename "$tmp")" | sed "s|$(basename "$tmp")|$(basename "$final")|") > "$checksum_tmp"
mv "$tmp" "$final"
mv "$checksum_tmp" "$final.sha256"
published=1
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'medipredict-*.dump' -mtime "+$RETENTION_DAYS" -print -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'medipredict-*.dump.sha256' -mtime "+$RETENTION_DAYS" -delete
printf 'Backup created: %s\n' "$final"
