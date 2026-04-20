# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Story 6.2 — Grafana dashboard JSON sanity (no live Grafana)."""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DASHBOARD = _REPO_ROOT / "docs" / "observability" / "grafana" / "dirijor-realm-health.json"


def test_realm_health_dashboard_json_loads_and_has_required_keys() -> None:
    raw = _DASHBOARD.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data.get("uid") == "dirijor-realm-health"
    assert str(data.get("uid", "")).startswith("dirijor-")
    assert data.get("title")
    assert isinstance(data.get("panels"), list)
    assert len(data["panels"]) >= 1
    assert data.get("schemaVersion", 0) >= 38
    assert "Realm health" in (data.get("title") or "")
