# Template manifest (v1)

Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

This document is the **authoritative reference** for swarm/realm **template manifests** (Epic 7, Story 7.1). Story 7.2 consumes only manifests that pass `verify_template_manifest` in Core.

## Schema identity

| Field | v1 value |
|-------|----------|
| `manifest_schema` | `dirijor.template_manifest.v1` (closed literal) |

**Source of truth:** Pydantic models in `backend/dirijor-core/template_manifest.py`.

**Derived JSON Schema** (for CI and non-Python consumers): [`schemas/dirijor.template_manifest.v1.json`](schemas/dirijor.template_manifest.v1.json). Regenerate after model changes:

```bash
cd backend/dirijor-core && python -c "import json, template_manifest as t; print(json.dumps(t.template_manifest_v1_json_schema(), indent=2, sort_keys=True))" > ../../docs/reference/schemas/dirijor.template_manifest.v1.json
```

Unknown keys anywhere in the wire JSON are **rejected** (`extra="forbid"` in Pydantic). There is **no** silent ignore in v1.

### Out of scope for v1

The following are **not** part of v1 (no optional placeholders): `updated_at`, manifest TTL, and time-based revocation lists. A future schema bump may add them.

## Required fields (summary)

| Field | Meaning |
|-------|---------|
| `template_id` | Stable string identifier for the template. |
| `template_version` | Semver string `major.minor.patch` (e.g. `1.2.0`). |
| `manifest_schema` | Must be `dirijor.template_manifest.v1`. |
| `created_at` | UTC timestamp, ISO-8601 with `Z` suffix. |
| `agents` | Non-empty list of agent slots (see below). |
| `policy_refs` | Structured **references** to policy artifacts (not embedded secrets). |
| `pins` | Version and environment pins (see **Pin semantics**). |
| `signatures` | Embedded signature list (see **Signing**). Non-empty in v1. |

### `agents[]`

Each element includes:

- `agent_id` — stable id (string, non-empty).
- `role` — non-empty string.
- `runtime_hint` / `tooling_hint` — optional, **non-secret** labels only.

### `policy_refs[]`

Each element includes:

- `kind` — one of `egress_policy`, `hitl_policy`, `tool_policy`.
- `uri` — opaque reference (URL, URN, or repo-relative id) **without** embedded credentials.
- `version` — optional semver string when the policy artifact is versioned.

These are **references** aligned at a high level with Story 2.3 egress semantics (default-deny posture is expressed by policy objects, not by a hidden “public egress default true” flag inside the manifest).

### `pins`

See **Pin semantics** below.

## Pin semantics (v1)

### `pins.supervisor_schema_version`

- Type: semver string `major.minor.patch`.
- Meaning: **minimum** Core HTTP contract floor: the supervisor’s integer `SCHEMA_VERSION` (see `supervisor.py`) is mapped to semver as **`N.0.0`** (e.g. `8` → `8.0.0`).
- Verification compares using semver ordering: Core is **too old** if `N.0.0` is **strictly below** the manifest minimum → verification fails with code **`PINS`**.

### Other `pins` fields (v1)

Any other declared pin fields (e.g. `adapter_hint`) use **exact string equality** when present: callers pass **`pin_bindings`** into `verify_template_manifest` with the expected strings from the runtime. There are **no** ranges in v1 unless a future schema adds an explicit `min_`-style field.

## Canonical serialization (signing)

Verification uses **one** algorithm:

- **UTF-8 JSON** with **recursively sorted object keys** and no insignificant whitespace (`separators=(',', ':')`, `ensure_ascii=False`).

**Signing payload:** the canonical JSON bytes of the manifest object **with the `signatures` key omitted** (content only). The same bytes are authenticated by the signature algorithms. Embedded `signatures` on the wire cover the single-file marketplace artifact; detached `manifest.sig` is not the default in v1 (alternate only if documented separately).

**Not used in v1:** RFC 8785 JSON Canonicalization Scheme (JCS), unless product/security later requires interoperability — would need a schema bump and explicit tests.

## Signing algorithms

| `algorithm` | Behavior in Core v1 |
|---------------|----------------------|
| `hmac-sha256` | HMAC-SHA256 over the signing payload. **Verifier key:** environment variable `DIRIJOR_TEMPLATE_MANIFEST_HMAC_KEY` (UTF-8). Suitable for dev/CI and controlled operator environments. Value is base64-encoded raw digest (32 bytes). |
| `none` | **Explicit stub** — no cryptographic integrity. Document honestly; do not treat as tamper protection. |
| `ed25519` | **Not implemented** in Core today (no bundled verifier). Manifests using only this algorithm fail verification until a future dependency decision. |

**Preference:** Ed25519 for public verifiability in a future revision; HMAC or `none` as above for current shipped code.

## Verification API

Pure function (no network):

```text
verify_template_manifest(raw: bytes, *, effective_supervisor_schema_version: int, pin_bindings: dict[str, str] | None) -> Success | Failure
```

### Error taxonomy (closed)

| Code | Meaning |
|------|---------|
| `PARSE` | Invalid UTF-8 or invalid JSON. |
| `SCHEMA` | Pydantic validation failed (including unknown keys). |
| `SIGNATURE` | Missing/invalid key, wrong MAC, tamper, or unsupported algorithm. |
| `PINS` | Supervisor semver floor failure or exact-string pin mismatch. |

Story 7.2 and docs should use **only** these codes, not ad-hoc strings per call site.

## Trust & safety (FR12, NFR6)

Manifests **must not** embed cloud credentials, Terraform state, mesh keys, or raw tool bodies. Use **references**, hashes, or non-secret labels only. Private-by-default posture is preserved by referencing policy artifacts (e.g. egress policy URIs) rather than encoding unsafe defaults as implicit flags.

## HTTP surface

Story 7.1 ships **library verification + docs + tests** only. Read-only marketplace HTTP (if any) is deferred unless added in a later story with a `SCHEMA_VERSION` bump per [`supervisor-api.md`](supervisor-api.md). See the short pointer subsection there.

## Golden example (illustrative)

See unit tests in `backend/dirijor-core/tests/test_template_manifest.py` for a full round-trip with `hmac-sha256` and `none`.
