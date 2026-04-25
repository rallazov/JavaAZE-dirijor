#!/usr/bin/env bash
# Verify Dirijor Core readiness: GET /health must return HTTP 200.
# Requires: curl in PATH.
# Usage: from repo root, with supervisor listening (default http://localhost:8000):
#   ./scripts/verify-golden-path.sh
# Optional: DIRIJOR_VERIFY_BASE=https://host:port — supervisor origin only
# (scheme + host + port; no URL path, no trailing slash). Appends /health to that origin.
# Exit: 0 if /health is 200; 1 if not ready; 2 if BASE URL is invalid (path/query/userinfo).

set -euo pipefail

BASE_URL="${DIRIJOR_VERIFY_BASE:-http://localhost:8000}"
BASE_URL="${BASE_URL%/}"
if [[ "$BASE_URL" != http://* && "$BASE_URL" != https://* ]]; then
  echo "FAIL: DIRIJOR_VERIFY_BASE must include http:// or https://. Got: ${BASE_URL}" >&2
  exit 2
fi
# Origin only: reject path, query, or fragment (e.g. .../v1 breaks /health).
authority="${BASE_URL#*://}"
if [[ "$authority" == */* || "$authority" == *[\?\#]* || "$authority" == *@* ]]; then
  echo "FAIL: DIRIJOR_VERIFY_BASE must be supervisor origin only (scheme://host:port), no path, query, userinfo, or fragment. Got: ${BASE_URL}" >&2
  exit 2
fi
url="${BASE_URL}/health"

code="$(curl -sS -o /dev/null -w '%{http_code}' "$url" || true)"

if [[ "$code" == "200" ]]; then
  echo "OK: GET ${url} -> HTTP 200"
  exit 0
fi

echo "FAIL: GET ${url} -> HTTP ${code:-000} (expected 200). Is the supervisor up?" >&2
exit 1
