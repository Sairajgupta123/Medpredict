#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/backups"
export PATH="$TMP/bin:$PATH"
export DATABASE_URL='postgresql://backup_user@localhost:5432/medipredict'
export PGPASSFILE="$TMP/pgpass"
export BACKUP_DIR="$TMP/backups"
export RESTORE_LOG="$TMP/restore.log"
printf 'localhost:5432:medipredict:backup_user:secret\n' > "$PGPASSFILE"
chmod 600 "$PGPASSFILE"

cat > "$TMP/bin/pg_dump" <<'FAKE_DUMP'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${FAKE_DUMP_FAIL:-0}" == "1" ]]; then exit 9; fi
for arg in "$@"; do
  case "$arg" in --file=*) printf 'valid fake custom archive\n' > "${arg#--file=}" ;; esac
done
FAKE_DUMP
cat > "$TMP/bin/psql" <<'FAKE_PSQL'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "${FAKE_PSQL_OBJECTS:-0}"
FAKE_PSQL
cat > "$TMP/bin/pg_restore" <<'FAKE_RESTORE'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1:-}" == "--list" ]]; then
  [[ -s "$2" ]] || exit 1
  exit 0
fi
printf 'restore invoked\n' >> "$RESTORE_LOG"
FAKE_RESTORE
chmod +x "$TMP/bin/pg_dump" "$TMP/bin/psql" "$TMP/bin/pg_restore"

bash "$ROOT/postgres-backup.sh"
shopt -s nullglob
archives=("$BACKUP_DIR"/medipredict-*.dump)
[[ "${#archives[@]}" -eq 1 ]]
[[ -s "${archives[0]}.sha256" ]]
(cd "$BACKUP_DIR" && sha256sum --check "$(basename "${archives[0]}").sha256")
# Exercise the exact checksum emitted by the backup script, not a reconstructed one.
ALLOW_DATABASE_RESTORE=YES BACKUP_FILE="${archives[0]}" bash "$ROOT/postgres-restore.sh"
grep -q "restore invoked" "$RESTORE_LOG"
rm -f "$RESTORE_LOG"

# Restore must fail closed without the explicit isolated-target acknowledgement.
if ALLOW_DATABASE_RESTORE=NO BACKUP_FILE="${archives[0]}" bash "$ROOT/postgres-restore.sh" >/dev/null 2>&1; then
  echo "Restore unexpectedly accepted missing acknowledgement." >&2; exit 1
fi
[[ ! -e "$RESTORE_LOG" ]]

# A non-empty restore target must be rejected before pg_restore is invoked.
if FAKE_PSQL_OBJECTS=2 ALLOW_DATABASE_RESTORE=YES BACKUP_FILE="${archives[0]}" bash "$ROOT/postgres-restore.sh" >/dev/null 2>&1; then
  echo "Restore unexpectedly accepted a non-empty target." >&2; exit 1
fi
[[ ! -e "$RESTORE_LOG" ]]

# A modified backup must fail checksum verification and never invoke pg_restore.
printf 'tampered\n' >> "${archives[0]}"
if ALLOW_DATABASE_RESTORE=YES BACKUP_FILE="${archives[0]}" bash "$ROOT/postgres-restore.sh" >/dev/null 2>&1; then
  echo "Restore unexpectedly accepted a checksum mismatch." >&2; exit 1
fi
[[ ! -e "$RESTORE_LOG" ]]

# A checksum that names a different archive must not authorize this restore.
printf 'valid fake custom archive\n' > "${archives[0]}"
(cd "$BACKUP_DIR" && sha256sum "$(basename "${archives[0]}")" > "$(basename "${archives[0]}").sha256")
sed -i 's/medipredict-[0-9]*T[0-9]*Z.dump/medipredict-20000101T000000Z.dump/' "${archives[0]}.sha256"
if ALLOW_DATABASE_RESTORE=YES BACKUP_FILE="${archives[0]}" bash "$ROOT/postgres-restore.sh" >/dev/null 2>&1; then
  echo "Restore unexpectedly accepted a checksum for a different filename." >&2; exit 1
fi
[[ ! -e "$RESTORE_LOG" ]]

# A valid checksum and explicit acknowledgement allow the restore command.
(cd "$BACKUP_DIR" && sha256sum "$(basename "${archives[0]}")" > "$(basename "${archives[0]}").sha256")
ALLOW_DATABASE_RESTORE=YES BACKUP_FILE="${archives[0]}" bash "$ROOT/postgres-restore.sh"
grep -q 'restore invoked' "$RESTORE_LOG"

# A failed dump must leave no published archive or stale partial file.
export BACKUP_DIR="$TMP/failed-backups"
mkdir -p "$BACKUP_DIR"
if FAKE_DUMP_FAIL=1 bash "$ROOT/postgres-backup.sh" >/dev/null 2>&1; then
  echo "Backup unexpectedly succeeded after pg_dump failure." >&2; exit 1
fi
if find "$BACKUP_DIR" -maxdepth 1 -type f -print -quit | grep -q .; then
  echo "Failed backup left a published or partial file." >&2; exit 1
fi
[[ ! -e "$BACKUP_DIR/.medipredict-backup.lock" ]]

echo "PostgreSQL backup/restore safety tests passed."
