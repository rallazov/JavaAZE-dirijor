#!/bin/sh
# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
# Story 9.4: mesh mode binds Core to loopback; tailnet peers reach via `tailscale serve`.
set -e
port="${DIRIJOR_SUPERVISOR_PORT:-8000}"
enabled="$(printf %s "${DIRIJOR_SUPERVISOR_MESH_ENABLED:-}" | tr '[:upper:]' '[:lower:]')"
case "$enabled" in
  1|true|yes)
    exec python -m uvicorn supervisor:app --host 127.0.0.1 --port "$port"
    ;;
  *)
    exec python -m uvicorn supervisor:app --host 0.0.0.0 --port "$port"
    ;;
esac
