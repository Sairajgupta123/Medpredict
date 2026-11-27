#!/usr/bin/env bash
# Run an approved MediPredict worker while emitting only low-cardinality status.
set -Eeuo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "Usage: bash deployment/run-worker.sh <worker-name>" >&2
  exit 2
fi

case "$1" in
  account-deletion)
    module="app.workers.account_deletion"
    label="account_deletion"
    ;;
  skin-image-retention)
    module="app.workers.skin_image_retention"
    label="skin_image_retention"
    ;;
  auth-rate-limit-cleanup)
    module="app.workers.auth_rate_limit_cleanup"
    label="auth_rate_limit_cleanup"
    ;;
  email-verification-cleanup)
    module="app.workers.email_verification_cleanup"
    label="email_verification_cleanup"
    ;;
  *)
    echo "Unknown worker name; refusing to execute arbitrary module." >&2
    exit 2
    ;;
esac

timeout_seconds="${WORKER_TIMEOUT_SECONDS:-900}"
if ! [[ "$timeout_seconds" =~ ^[0-9]+$ ]] || (( timeout_seconds < 1 || timeout_seconds > 86400 )); then
  echo "WORKER_TIMEOUT_SECONDS must be an integer from 1 to 86400." >&2
  exit 2
fi
command -v timeout >/dev/null || { echo "timeout command is required." >&2; exit 127; }
command -v python >/dev/null || { echo "python command is required." >&2; exit 127; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
started="$(date +%s)"
set +e
timeout "${timeout_seconds}s" python -m "$module" >"$tmp" 2>&1
worker_status=$?
set -e
finished="$(date +%s)"
duration=$((finished - started))

# Worker output is intentionally not replayed: exception text may contain sensitive
# values. Emit only the known aggregate summary formats and a bounded status record.
case "$label" in
  account_deletion)
    summary_pattern='^Account deletion batch: processed=[0-9]+ completed=[0-9]+ failed=[0-9]+$'
    ;;
  skin_image_retention)
    summary_pattern='^Skin-image retention batch: processed=[0-9]+ deleted=[0-9]+ failed=[0-9]+$'
    ;;
  auth_rate_limit_cleanup)
    summary_pattern='^Authentication rate-limit cleanup: deleted=[0-9]+$'
    ;;
  email_verification_cleanup)
    summary_pattern='^Email verification token cleanup: deleted=[0-9]+$'
    ;;
esac
summary="$(grep -E "$summary_pattern" "$tmp" | tail -n 1 || true)"
if [[ -n "$summary" ]]; then
  printf '%s\n' "$summary"
else
  printf 'worker_summary=unavailable\n'
fi
printf 'worker_run name=%s status=%s exit_code=%s duration_seconds=%s\n' \
  "$label" "$([[ "$worker_status" -eq 0 ]] && echo success || echo failure)" \
  "$worker_status" "$duration"
exit "$worker_status"
