# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Versioned anomaly / quarantine policy (Story 4.2).

v0 uses JSON only (no PyYAML dependency). Load via ``DIRIJOR_ANOMALY_POLICY_PATH``;
an empty value means an in-memory empty ruleset (operators may add rules later via file).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

# --- Models -------------------------------------------------------------------


class WhenConsensusScoreBelow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["consensus_score_below"] = "consensus_score_below"
    threshold: float


class WhenConsensusTerminationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["consensus_termination_in"] = "consensus_termination_in"
    reasons: list[str] = Field(min_length=1)


class WhenSignalTypeEq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["signal_type_eq"] = "signal_type_eq"
    signal_type: str = Field(min_length=1)


class WhenToolNameRegex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_name_regex"] = "tool_name_regex"
    pattern: str = Field(min_length=1)

    @field_validator("pattern")
    @classmethod
    def _must_compile(cls, v: str) -> str:
        re.compile(v)
        return v


WhenClause = Annotated[
    Union[
        WhenConsensusScoreBelow,
        WhenConsensusTerminationIn,
        WhenSignalTypeEq,
        WhenToolNameRegex,
    ],
    Field(discriminator="type"),
]


class AnomalyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    description: str = ""
    when: WhenClause
    action: Literal["quarantine"] = "quarantine"


class AnomalyPolicyDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[AnomalyRule] = Field(default_factory=list)


_POLICY_ADAPTER = TypeAdapter(AnomalyPolicyDocument)


def load_anomaly_policy_from_path(path: str | None) -> tuple[AnomalyPolicyDocument | None, str | None]:
    """Parse and validate a policy file.

    Returns ``(document, None)`` on success. On failure returns ``(None, detail)``
    where ``detail`` is safe to surface on ``/health`` (short string).

    * Missing / empty ``path`` → empty ruleset (no error).
    * Non-empty ``path`` → must be a readable JSON file matching
      :class:`AnomalyPolicyDocument`.
    """
    if path is None or not str(path).strip():
        return AnomalyPolicyDocument(rules=[]), None
    p = Path(path.strip())
    if not p.is_file():
        return None, f"anomaly policy path is not a file: {p}"
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
        doc = _POLICY_ADAPTER.validate_python(data)
        return doc, None
    except json.JSONDecodeError as exc:
        return None, f"anomaly policy JSON invalid: {exc}"
    except Exception as exc:  # ValidationError and other Pydantic errors
        return None, f"anomaly policy invalid: {exc}"


def rule_matches_consensus(rule: AnomalyRule, *, consensus_score: float, termination_reason: str) -> bool:
    w = rule.when
    if isinstance(w, WhenConsensusScoreBelow):
        return consensus_score < w.threshold
    if isinstance(w, WhenConsensusTerminationIn):
        return termination_reason in w.reasons
    return False


def rule_matches_signal(rule: AnomalyRule, *, signal_type: str, tool_name: str | None) -> bool:
    w = rule.when
    if isinstance(w, WhenSignalTypeEq):
        return signal_type == w.signal_type
    if isinstance(w, WhenToolNameRegex):
        if not tool_name:
            return False
        try:
            return re.search(w.pattern, tool_name) is not None
        except re.error:
            return False
    return False
