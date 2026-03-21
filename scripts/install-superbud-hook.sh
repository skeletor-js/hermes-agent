#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${REPO_ROOT}/deploy/hooks/superbud-memory"
TARGET_DIR="${HOME}/.hermes/hooks/superbud-memory"

if [[ "${1:-}" == "--check" ]]; then
  [[ -f "${TARGET_DIR}/HOOK.yaml" ]] || { echo "missing ${TARGET_DIR}/HOOK.yaml"; exit 1; }
  [[ -f "${TARGET_DIR}/handler.py" ]] || { echo "missing ${TARGET_DIR}/handler.py"; exit 1; }
  diff -q "${SOURCE_DIR}/HOOK.yaml" "${TARGET_DIR}/HOOK.yaml" >/dev/null || { echo "HOOK.yaml differs from tracked version"; exit 1; }
  diff -q "${SOURCE_DIR}/handler.py" "${TARGET_DIR}/handler.py" >/dev/null || { echo "handler.py differs from tracked version"; exit 1; }
  echo "superbud hook matches tracked version"
  exit 0
fi

mkdir -p "${TARGET_DIR}"
install -m 0644 "${SOURCE_DIR}/HOOK.yaml" "${TARGET_DIR}/HOOK.yaml"
install -m 0644 "${SOURCE_DIR}/handler.py" "${TARGET_DIR}/handler.py"

echo "installed tracked superbud-memory hook to ${TARGET_DIR}"
echo "state.json and entities.json were left untouched"
