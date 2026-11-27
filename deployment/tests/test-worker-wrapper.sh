#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
export PATH="$TMP/bin:$PATH"
export FAKE_WORKER_STATUS=0
export FAKE_WORKER_SUMMARY="Account deletion batch: processed=2 completed=2 failed=0 possible_backlog=false"

cat > "$TMP/bin/python" <<'FAKE_PYTHON'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$1" == "-m" && "$2" == "app.workers.account_deletion" ]]
printf '%s\n' "$FAKE_WORKER_SUMMARY"
printf 'sensitive-stdout@example.test image-key=do-not-print\n'
printf 'sensitive-stderr@example.test token=do-not-print\n' >&2
if [[ "\${FAKE_WORKER_SLEEP:-0}" == "1" ]]; then sleep 3; fi
exit "$FAKE_WORKER_STATUS"
FAKE_PYTHON
chmod +x "$TMP/bin/python"

output="$(bash "$ROOT/run-worker.sh" account-deletion 2>&1)"
grep -q 'Account deletion batch: processed=2 completed=2 failed=0' <<<"$output"
grep -q 'worker_run name=account_deletion status=success exit_code=0 duration_seconds=' <<<"$output"
if grep -q 'sensitive-stdout@example.test\|sensitive-stderr@example.test\|image-key=do-not-print\|token=do-not-print' <<<"$output"; then
  echo "Worker wrapper leaked raw worker output." >&2; exit 1
fi

export FAKE_WORKER_STATUS=7
if output="$(bash "$ROOT/run-worker.sh" account-deletion 2>&1)"; then
  echo "Worker wrapper unexpectedly accepted a failed worker." >&2; exit 1
else
  status=$?
  [[ "$status" -eq 7 ]]
fi
grep -q 'worker_run name=account_deletion status=failure exit_code=7 duration_seconds=' <<<"$output"
if grep -q 'sensitive-stdout@example.test\|sensitive-stderr@example.test\|image-key=do-not-print\|token=do-not-print' <<<"$output"; then
  echo "Worker wrapper leaked output after failure." >&2; exit 1
fi

if WORKER_TIMEOUT_SECONDS=1 FAKE_WORKER_SLEEP=1 output="$(bash "$ROOT/run-worker.sh" account-deletion 2>&1)"; then
  echo "Worker wrapper unexpectedly accepted a timed-out worker." >&2; exit 1
else
  status=$?
  [[ "$status" -eq 124 ]]
fi
grep -q 'worker_run name=account_deletion status=failure exit_code=124 duration_seconds=' <<<"$output"
if grep -q 'sensitive-stdout@example.test\|sensitive-stderr@example.test\|image-key=do-not-print\|token=do-not-print' <<<"$output"; then
  echo "Worker wrapper leaked output from a timed-out worker." >&2; exit 1
fi

if bash "$ROOT/run-worker.sh" arbitrary-python-module >/dev/null 2>&1; then
  echo "Worker wrapper accepted an arbitrary module." >&2; exit 1
fi
if WORKER_TIMEOUT_SECONDS=0 bash "$ROOT/run-worker.sh" account-deletion >/dev/null 2>&1; then
  echo "Worker wrapper accepted an invalid timeout." >&2; exit 1
fi

echo "Privacy-safe worker wrapper tests passed."
