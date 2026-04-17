# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Make the `dirijor-core` module root importable when pytest is invoked
from the repository root (e.g. ``python -m pytest backend/dirijor-core/tests``).

Tests exercise the in-process FastAPI app via ``fastapi.testclient.TestClient`` —
no real network, no uvicorn boot (AC 6).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SUPERVISOR_ROOT = Path(__file__).resolve().parent.parent
if str(_SUPERVISOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUPERVISOR_ROOT))
