# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Realm HUD metrics aggregation for Story 6.3 (`metrics.update` WebSocket frames).

v1 derives numbers from supervisor-authoritative state and the in-process audit
ring — not from Tempo/Grafana/Prometheus in the browser. Optional Core-side
queries to observability backends are deferred (see deferred-work.md).
"""

from __future__ import annotations

from typing import Any

import audit_export as audit_export_lib


def compute_hud_latency_ms(
    *,
    consensus_score: float | None,
    consensus_rounds: int | None,
    quarantine_unique_agent_count: int,
) -> int:
    """Supervisor-derived latency estimate (ms), bounded and deterministic.

    Definition: base RTT + small additive terms from consensus rounds, score
    shortfall, and quarantine pressure. This is **best-effort** vs Grafana
    TraceQL latency panels (6.2), which may sample different spans.
    """

    base = 28
    rounds = consensus_rounds if consensus_rounds is not None else 1
    base += min(32, max(0, rounds - 1) * 5)
    if consensus_score is not None:
        gap = max(0.0, 1.0 - float(consensus_score))
        base += int(min(48.0, gap * 80.0))
    base += min(72, quarantine_unique_agent_count * 14)
    return max(1, min(2500, int(base)))


def compute_security_posture(quarantine_unique_agent_count: int) -> int:
    """0–100 aggregate posture; degrades with quarantined agents (unique ids)."""

    return max(0, min(100, 95 - 8 * quarantine_unique_agent_count))


async def build_realm_metrics_snapshot(
    realm_id: str,
    *,
    quarantine_unique_agent_count: int,
    consensus_score: float | None,
    consensus_rounds: int | None,
) -> dict[str, Any]:
    """CamelCase JSON dict for `metrics.update` shallow-merge on the canvas."""

    audit_preview = await audit_export_lib.hud_audit_preview_entries(
        realm_id, limit=5
    )
    return {
        "latencyMs": compute_hud_latency_ms(
            consensus_score=consensus_score,
            consensus_rounds=consensus_rounds,
            quarantine_unique_agent_count=quarantine_unique_agent_count,
        ),
        "securityPosture": compute_security_posture(quarantine_unique_agent_count),
        "auditPreview": audit_preview,
        "quarantinedAgentCount": quarantine_unique_agent_count,
    }
