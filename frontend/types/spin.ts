// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
//
// Canvas ↔ Core realm-spin types (Story 2.1, schema v3).
//
// INVARIANT: field names in this file MUST mirror the backend Pydantic
// models in `backend/dirijor-core/supervisor.py` (search the
// `# --- Realm spin (Story 2.1) ---` block). If a backend field name
// changes, fix THIS file — not the backend — so `frontend/lib/dirijor-api.ts`
// stays a pure pass-through with zero key-renaming. Same rule as
// `types/realtime.ts`.
//
// Adding a new `SpinPhase` member or a new `SpinErrorBody.code` value
// requires a backend contract change in the same PR (closed enums, see
// AC 2 of Story 2.1). Do NOT widen `SpinPhase` client-side to paper
// over a backend gap.

export type SpinPhase = 'validating' | 'provisioning' | 'ready' | 'failed';

/** POST /realms/spin request body. `ConfigDict(extra="forbid")` on the
 *  backend side rejects unknown keys, so keep this interface exact. */
export interface SpinRequest {
  realm_description: string;
  adapter_hint?: string;
  realm_id?: string;
  agent_count?: number;
}

/** POST /realms/spin 202 response body. */
export interface SpinResponse {
  job_id: string;
  realm_id: string;
  phase: SpinPhase;
  adapter: string;
  /** ISO-8601 UTC with trailing Z. */
  created_at: string;
  status_url: string;
  schema_version: number;
}

/** Structured error envelope used on every non-2xx path
 *  (400 / 404 / 409 / 503). `code` is a closed enum; see the top of
 *  `dirijor-api.ts` for the backend-vs-client split. */
export interface SpinErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

/** GET /realms/{job_id} 200 response body — full job state. */
export interface SpinJob extends SpinResponse {
  /** ISO-8601 UTC with trailing Z. Advances monotonically on every
   *  phase transition. */
  updated_at: string;
  realm_description: string;
  agent_count: number;
  /** Populated only when `phase === "ready"`; `{}` otherwise. */
  outputs: Record<string, unknown>;
  /** Populated only when `phase === "failed"`; `null` otherwise. */
  error: SpinErrorBody | null;
}
