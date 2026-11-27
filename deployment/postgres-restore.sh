#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
: "${DATABASE_URL:?Set DATABASE_URL to the isolated restore target}"
: "${PGPASSFILE:?Set PGPASSFILE to a protected PostgreSQL password file}"
: "${BACKUP_FILE:?Set BACKUP_FILE to the .dump backup file}"
: "${ALLOW_DATABASE_RESTORE:?Set ALLOW_DATABASE_RESTORE=YES after verifying the target is isolated}"
if [[ "$ALLOW_DATABASE_RESTORE" != "YES" ]]; then
  echo "Restore blocked. Set ALLOW_DATABASE_RESTORE=YES only for an isolated, disposable target." >&2; exit 2
fi
if [[ "$DATABASE_URL" == *"://"* && "$DATABASE_URL" == *"://*:*@"* ]]; then
  echo "Refusing DATABASE_URL containing an inline password; use PGPASSFILE." >&2; exit 2
fi
command -v pg_restore >/dev/null || { echo "pg_restore is required." >&2; exit 127; }
command -v psql >/dev/null || { echo "psql is required to verify the restore target is empty." >&2; exit 127; }
command -v sha256sum >/dev/null || { echo "sha256sum is required." >&2; exit 127; }
[[ -f "$PGPASSFILE" ]] || { echo "PGPASSFILE does not exist." >&2; exit 2; }
[[ -s "$BACKUP_FILE" ]] || { echo "Backup file is missing or empty." >&2; exit 2; }
[[ -f "$BACKUP_FILE.sha256" ]] || { echo "Backup checksum file is missing." >&2; exit 2; }
backup_name="$(basename "$BACKUP_FILE")"
if ! [[ "$backup_name" =~ ^medipredict-[0-9]{8}T[0-9]{6}Z\.dump$ ]]; then
  echo "Backup filename does not match the expected archive format." >&2; exit 2
fi
chmod 600 "$PGPASSFILE"
checksum_line="$(cat "$BACKUP_FILE.sha256")"
if ! [[ "$checksum_line" =~ ^([[:xdigit:]]{64})[[:space:]]+\*?${backup_name}$ ]]; then
  echo "Backup checksum file has an invalid format or filename." >&2; exit 2
fi
expected_checksum="${BASH_REMATCH[1],,}"
actual_checksum="$(sha256sum "$BACKUP_FILE" | cut -d ' ' -f 1)"
if [[ "$actual_checksum" != "$expected_checksum" ]]; then
  echo "Backup checksum verification failed." >&2; exit 2
fi
# Refuse to merge into an existing database: restore is permitted only into an empty target.
object_count="$(psql --no-password --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 "$DATABASE_URL" --command="SELECT (SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')) + (SELECT count(*) FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname NOT IN ('pg_catalog', 'information_schema'));")"
if ! [[ "$object_count" =~ ^[0-9]+$ ]] || (( object_count != 0 )); then
  echo "Restore target is not empty or could not be verified; refusing to restore." >&2; exit 2
fi
pg_restore --no-password --exit-on-error --no-owner --no-privileges --dbname="$DATABASE_URL" "$BACKUP_FILE"
echo "Restore completed. Run application smoke tests and verify the Alembic revision before routing traffic."
