<!--
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
-->

# Observability — Grafana realm health (Story 6.2)

This folder holds **dashboard-as-code** for operators. Traces are produced by **Story 6.1** (`dirijor-core`, `dirijor-openclaw-wrapper`) and are **opt-in** via `OTEL_EXPORTER_OTLP_ENDPOINT`.

## Grafana version

Dashboard JSON targets **Grafana 10.4+** (`schemaVersion` **39** in the export). Older Grafana versions may require re-export or minor panel tweaks.

## Dashboard artifact

| Item | Location |
|------|----------|
| **Realm health** dashboard | [`grafana/dirijor-realm-health.json`](grafana/dirijor-realm-health.json) |
| **Stable UID** | `dirijor-realm-health` (prefix `dirijor-*`) |

Import in Grafana: **Dashboards → New → Import → Upload JSON**, or use the optional Compose stack below (auto-loads from provisioning).

### Datasource assumptions

- **Tempo** datasource UID **`tempo`** (matches `ops/observability/grafana-provisioning/datasources/datasources.yaml`).
- Panels use **TraceQL** against traces. **HTTP latency** for routes uses server spans with `span.http.route` (if your Tempo/OTel semconv version uses a different TraceQL field name, adjust the query in Grafana — empty panels usually mean a selector mismatch).
- **Failures (AC3):** For Story 6.2, **TraceQL panels that list traces with `status = error`** provide per-service, per-operation failure visibility (count via the trace list / time range). **Numeric error-rate time series** (errors/s) require Tempo **metrics generator** + **Prometheus** — a follow-up beyond this slice.
- **Aggregate latency histograms** (p50/p95 over time) require **Tempo metrics generator** + **Prometheus** (or Grafana Cloud) — not bundled in the minimal Compose profile. Until then, use trace rows (duration per trace) or **Explore** for drill-down.

### Span inventory (panels)

| Area | Span / signal | `dirijor.realm_id` |
|------|----------------|-------------------|
| HTTP API | FastAPI server spans (`http.route`) | When handlers set it |
| Realm spin | `dirijor.realm.spin_job` | Yes (when in spin path) |
| Realm destroy | `dirijor.realm.destroy_job` | Yes |
| Consensus | `dirijor.consensus` | Set when request includes realm |
| Terraform | `dirijor.terraform.subprocess` | Yes |
| Mesh | `dirijor.mesh.bootstrap`, `dirijor.mesh.bootstrap.ready_realm` | Yes |
| Realtime | `dirijor.realtime.broadcast`, `dirijor.ws.realm_session` | Yes |
| OpenClaw | `dirijor.wrapper.tools.invoke` | Wrapper resource only |
| Quarantine | `dirijor.safety.quarantine_record` (Story 6.2) | Yes (`dirijor.realm_id`, `dirijor.rule_id`, `dirijor.agent_id`) |

**Quarantine:** Implemented as a **low-cardinality manual span** `dirijor.safety.quarantine_record` on the **`emit_ws` notify path** (operator-visible broadcast/HITL), not on every silent registry merge. Alternative Loki queries are **not** required when this span is present.

### Span status vs HTTP status

See the in-dashboard **Documentation** row. Short version: **HTTP status** on auto-instrumented route spans reflects the response code; **manual Dirijor spans** use **span status** (`ERROR` vs `OK`) for operation failure.

## Local stack (optional Compose profile)

From the repo root:

```bash
docker compose --profile observability up -d
```

Services (pinned images in `docker-compose.yml`):

- **otel-collector** — OTLP gRPC **4317** and HTTP **4318** (published on localhost).
- **tempo** — trace backend; Grafana talks to `http://tempo:3200`.
- **grafana** — **http://127.0.0.1:3000** (defaults: **admin** / **admin**; set **`GRAFANA_ADMIN_USER`** / **`GRAFANA_ADMIN_PASSWORD`** in the environment before `docker compose up` if you are not on a solo dev machine).

Point processes at the collector (HTTP/protobuf, port **4318**):

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
export OTEL_SERVICE_NAME=dirijor-core   # or dirijor-openclaw-wrapper
```

For Compose **in-network** services (e.g. supervisor next to collector), use `http://otel-collector:4318`.

**Default `docker compose up` (no profile)** is unchanged — observability services are **not** started unless you pass `--profile observability`.

## Collector / Tempo config

- `ops/observability/otel-collector-config.yaml` — OTLP in → OTLP out to Tempo.
- `ops/observability/tempo.yaml` — minimal local storage.

## CI

Hermetic tests do **not** start Grafana. Dashboard JSON is validated in **pytest** (`backend/dirijor-core/tests/test_grafana_dashboards.py`).
