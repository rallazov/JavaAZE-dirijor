# OpenClaw wrapper (Dirijor)

Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

Agent runtime wrapper: **application-layer** enforcement for tool allowlists and egress checks. This complements **infrastructure** default-deny egress (Story 2.3 / [ADR-0004](../../docs/architecture/adr/0004-default-deny-egress-terraform.md)); do not treat this service as a substitute for firewall rules.

## HTTP API (v1)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` or `/health` | Process health + **policy summary** (counts and egress mode only — not full allowlists) |
| `POST` | `/v1/tools/invoke` | Body: `{ "tool": "name", "args": {} }`. Allowlist gate + stub execution or `501` |
| `POST` | `/v1/egress/check` | Body: `{ "url": "https://..." }`. Classifies URL **without DNS**; denies public targets in `deny_public` mode |

### Policy outcomes vs client/protocol errors

The wrapper distinguishes **policy-evaluated outcomes** (JSON parsed; allowlist / egress / not-implemented logic runs) from **pre-policy protocol errors** (body is not valid JSON, so handlers never evaluate policy).

- **Pre-policy:** `POST` bodies that are not JSON return **400** with `{ "error": "invalid_json", "wrapper_policy_version": "1" }` only. These responses **omit** `audit_id` and `realm` on purpose: no policy decision was made, and nothing is logged to the denial stream below (avoid implying a policy “denial” was recorded for bad JSON).
- **Universal non-2xx correlation:** If product later requires a single correlatable shape for every non-2xx (support/tracing), that is a separate contract choice from policy denials; today only policy outcomes use the denial envelope.

- **Request size:** If the raw body exceeds `DIRIJOR_WRAPPER_MAX_BODY_BYTES` (default **1048576**), the server responds **413** with `{ "error": "payload_too_large", "wrapper_policy_version": "1" }` (pre-policy; no `audit_id`).

### Denial responses (policy outcomes only)

When policy runs, blocked tools and disallowed egress attempts return JSON including at minimum:

- `error` — machine code (`tool_denied`, `egress_denied`, `not_implemented`, `invalid_request`, …)
- `realm`
- `tool` or `url` as applicable
- `audit_id` — UUID v4 for correlation
- `wrapper_policy_version` — `"1"`

Those denials are also logged to **stderr** as one JSON line per event (`component: openclaw-wrapper-denial`) with the same `audit_id`. The `url` field in logs is written with **userinfo redacted** (credentials are stripped) so secrets are not echoed to stderr.

## OpenTelemetry (Story 6.1)

This service uses the **OpenTelemetry JS SDK** (`@opentelemetry/sdk-trace-node`)
with an **OTLP HTTP** exporter when export is enabled. There is no separate
“API-only” tracing mode: spans are created for `GET /health`, `POST /v1/tools/invoke`,
and `POST /v1/egress/check`, but they are **no-op** until a `TracerProvider` with
an exporter is registered — `main.js` calls `initOtel()` which registers OTLP
export **only** when `OTEL_EXPORTER_OTLP_ENDPOINT` is non-empty and
`OTEL_SDK_DISABLED` is not truthy.

**Async context:** handlers run on Node’s HTTP `IncomingMessage` / `ServerResponse`
tick; span lifecycle is bound to the request callback. Nested async work inside
handlers continues on the same default executor — avoid `setImmediate` /
untracked pools if you need strict parent/child linkage for future code.

**Security:** span attributes include `dirijor.realm` and `http.route` only;
never put secrets, full tool arguments, or preauth material in attributes (same
posture as Story 5.2 logging).

## Environment variables

| Variable | Description |
|----------|-------------|
| `REALM_NAME` | Realm label for responses and logs (default `default-realm`) |
| `HEADSCALE_URL` | Shown in health JSON for mesh context (default `http://localhost:8080`) |
| `PORT` | Listen port (default `3001`) |
| `DIRIJOR_WRAPPER_BUILD_ID` | Optional string shown as `build` in `/health` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | If set, enables OTLP **HTTP** trace export (e.g. `http://localhost:4318/v1/traces` or collector base per exporter defaults). **Unset = no export.** |
| `OTEL_SERVICE_NAME` | Defaults to **`dirijor-openclaw-wrapper`**. |
| `OTEL_SERVICE_VERSION` | Optional build/version string for `service.version`. |
| `OTEL_SDK_DISABLED` | `true` / `1` / `yes` (case-insensitive) disables OTLP registration (aligned with Core). |
| `DIRIJOR_TOOL_ALLOWLIST` | Comma-separated tool names when **no** policy file is used. **Empty = deny all** tools on `/v1/tools/invoke`. |
| `DIRIJOR_WRAPPER_POLICY_PATH` | Optional path to JSON policy file. If set, the file **must** exist and parse; otherwise the process **exits on startup** (fail fast). |
| `DIRIJOR_EGRESS_MODE` | `deny_public` (default) or `allowlist` |
| `DIRIJOR_EGRESS_ALLOW_HOSTS` | Comma-separated hosts; used when `egress_mode` is `allowlist` to permit named public hosts (exact or subdomain match). |
| `DIRIJOR_IMPLEMENTED_TOOLS` | Optional comma-separated list. If set, allowlisted tools **not** in this set receive **HTTP 501** `not_implemented` (with `audit_id`) instead of stub success. |
| `DIRIJOR_WRAPPER_MAX_BODY_BYTES` | Max raw bytes read for `POST` JSON bodies (default **1048576**). Larger bodies yield **413** `payload_too_large`. |

### Policy file JSON

Used when `DIRIJOR_WRAPPER_POLICY_PATH` is set:

```json
{
  "tools": ["noop", "lookup"],
  "egress_mode": "deny_public",
  "egress_allow_hosts": ["api.partner.example"]
}
```

Fields:

- `tools` — array of allowed tool names (required shape when file is used; may be empty)
- `egress_mode` — optional; overrides `DIRIJOR_EGRESS_MODE` when present
- `egress_allow_hosts` — optional array; merges with env allow hosts semantics

## Run / test

```bash
npm test
npm start
```

Tests use Node’s built-in `node:test`. Story 6.1 adds OpenTelemetry runtime
dependencies for optional OTLP export; `test/otel.test.js` registers an
in-memory `TracerProvider` to assert span names without a collector.
