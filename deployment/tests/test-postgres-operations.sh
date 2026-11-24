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
for arg in "$@"; do
  case "$arg" in --file=*) printf 'valid fake custom archive\n' > "${arg#--file=}" ;; esac
done
FAKE_DUMP
cat > "$TMP/bin/pg_restore" <<'FAKE_RESTORE'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1:-}" == "--list" ]]; then
  [[ -s "$2" ]] || exit 1
  exit 0
fi
printf 'restore invoked\n' >> "$RESTORE_LOG"
FAKE_RESTORE
chmod +x "$TMP/bin/pg_dump" "$TMP/bin/pg_restore"

bash "$ROOT/postgres-backup.sh"
shopt -s nullglob
archives=("$BACKUP_DIR"/medipredict-*.dump)
[[ "${#archives[@]}" -eq 1 ]]
[[ -s "${archives[0]}.sha256" ]]
sha256sum --check "${archives[0]}.sha256"

# Restore must fail closed without the explicit isolated-target acknowledgement.
if ALLOW_DATABASE_RESTORE=NO BACKUP_FILE="${archives[0]}" bash "$ROOT/postgres-restore.sh" >/dev/null 2>&1; then
  echo "Restore unexpectedly accepted missing acknowledgement." >&2; exit 1
fi
[[ ! -e "$RESTORE_LOG" ]]

# A modified backup must fail checksum verification and never invoke pg_restore.
printf 'tampered\n' >> "${archives[0]}"
if ALLOW_DATABASE_RESTORE=YES BACKUP_FILE="${archives[0]}" bash "$ROOT/postgres-restore.sh" >/dev/null 2>&1; then
  echo "Restore unexpectedly accepted a checksum mismatch." >&2; exit 1
fi
[[ ! -e "$RESTORE_LOG" ]]

# A valid checksum and explicit acknowledgement allow the restore command.
printf 'valid fake custom archive\n' > "${archives[0]}"
(cd "$BACKUP_DIR" && sha256sum "$(basename "${archives[0]}")" > "$(basename "${archives[0]}").sha256")
ALLOW_DATABASE_RESTORE=YES BACKUP_FILE="${archives[0]}" bash "$ROOT/postgres-restore.sh"
grep -q 'restore invoked' "$RESTORE_LOG"

echo "PostgreSQL backup/restore safety tests passed."
