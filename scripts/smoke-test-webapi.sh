#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${HERMES_API_URL:-http://127.0.0.1:8642}"
TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-20}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

need curl

check() {
  local path="$1"
  local url="${BASE_URL}${path}"
  echo "==> GET ${url}"
  curl --silent --show-error --fail --max-time "${TIMEOUT_SECONDS}" "$url" >/tmp/hermes-smoke.out
  python3 - <<'PY'
from pathlib import Path
p = Path('/tmp/hermes-smoke.out')
text = p.read_text(errors='replace').strip()
print(text[:400] + ('...' if len(text) > 400 else ''))
PY
  echo
}

echo "Using BASE_URL=${BASE_URL}"
check "/health"
check "/v1/models"
check "/api/available-models"
check "/api/sessions"
check "/api/skills"
check "/api/memory"
check "/api/config"

echo "WebAPI smoke test passed"
