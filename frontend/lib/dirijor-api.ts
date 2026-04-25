// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
//
// Pure HTTP client for Dirijor Core Story 2.1 (realm spin) + forward
// extensions. Mirrors the `dirijor-realtime.ts` discipline:
//   - No React, no DOM mutations, no `process.env` reads outside the
//     `resolveDirijorApiUrl` helper. Pure functions + a thin fetch
//     wrapper that always returns a parsed domain type or throws a
//     typed `SpinApiError` — never a generic `Error`.
//   - Every non-2xx path on the backend speaks the `SpinError` envelope
//     (`{code, message, details}`); this module parses it and re-raises
//     as a `SpinApiError` so React consumers get a typed `.code`.
//   - Network failures (fetch throws, typically TypeError) and malformed
//     JSON responses are synthesized into the SAME error type with
//     client-only codes, so the UI never renders `undefined` fields.
//
// Env-var convention: `process.env.NEXT_PUBLIC_DIRIJOR_API_URL` is read
// ONLY by `useRealmSpin` (via `apiBase()` in `hooks/useRealmSpin.ts`).
// All other callers take a pre-resolved `base` string.
//
/**
 * SpinApiError.code union:
 *   Backend-originated (from SpinError envelope):
 *     validation_failed | invalid_realm_id | adapter_unknown
 *     | realm_id_conflict | realm_manager_unavailable
 *     | job_not_found | adapter_error | internal
 *     | terraform_init_failed | terraform_validate_failed | terraform_plan_failed
 *     | terraform_apply_failed | terraform_destroy_failed | terraform_command_timeout
 *     | adapter_credentials_missing | destroy_invalid_state | destroy_already_requested
 *   Client-synthesized (this module only):
 *     network_error  (fetch rejected, httpStatus=0)
 *     bad_response   (2xx body failed to parse or missing required keys)
 *     poll_timeout   (useRealmSpin hit POLL_TIMEOUT_MS before terminal phase)
 *
 * Future follow-up (post-2.1): lift `poll_timeout` to a backend code
 * if/when the spin runner grows a server-side provision timeout, so
 * both surfaces converge on one closed enum.
 */

import type { MarketplaceImportDraftSuccess } from '@/types/marketplace';
import type { SpinJob, SpinPhase, SpinRequest, SpinResponse } from '@/types/spin';

/** Runtime mirror of the closed `SpinPhase` union. Kept as a `const`
 *  `Set` so `isSpinResponse` / `isSpinJob` can reject a backend typo
 *  (`"provisionning"`) and synthesize a `bad_response` error rather
 *  than pass the unknown phase through to the React hook, which would
 *  loop the poller until `POLL_TIMEOUT_MS` fires. If `SpinPhase` gains
 *  a new member in `@/types/spin`, add the literal here in the same PR. */
const SPIN_PHASES: ReadonlySet<SpinPhase> = new Set<SpinPhase>([
  'validating',
  'provisioning',
  'ready',
  'failed',
]);

/** Default when `NEXT_PUBLIC_DIRIJOR_API_URL` is unset or blank. Matches
 *  the Dockerfile `EXPOSE 8000` + `docker-compose.yml` mapping. */
export const DEFAULT_API_BASE = 'http://localhost:8000';

/** Wall-time cap for `useRealmSpin` polling. Aligned to the PRD Success
 *  Criteria budget (`"Spin a 10-agent secure realm in <60 seconds"`);
 *  any adapter that blows past this is either stuck or pathological,
 *  and the hook synthesizes a `poll_timeout` error instead of looping
 *  forever. Exported from the pure module so consumers + tests share
 *  one literal. */
export const POLL_TIMEOUT_MS = 60_000;

/** Normalize `process.env.NEXT_PUBLIC_DIRIJOR_API_URL` into a well-formed
 *  base URL. Unlike `resolveDirijorWsUrl` (which returns `undefined` to
 *  keep the canvas runnable without a backend), this ALWAYS returns a
 *  string — the default points at the loopback supervisor. Trailing
 *  slashes are stripped so callers can concatenate `/realms/spin` etc.
 *  without worrying about `//`. */
export function resolveDirijorApiUrl(envVar: string | undefined): string {
  if (envVar === undefined || envVar === null) return DEFAULT_API_BASE;
  const trimmed = envVar.trim();
  if (trimmed.length === 0) return DEFAULT_API_BASE;
  return trimmed.replace(/\/+$/, '');
}

/** Typed error for every failure path in this module. `code` is either a
 *  backend `SpinError.code` or a client-synthesized code (see the block
 *  comment at the top of this file for the split). React consumers
 *  (`useRealmSpin` → `RealmToolbar`) render `error.code: error.message`
 *  without ever needing `instanceof` narrowing. */
export class SpinApiError extends Error {
  readonly code: string;
  readonly httpStatus: number;
  readonly details: Record<string, unknown>;

  constructor(
    code: string,
    message: string,
    httpStatus: number,
    details: Record<string, unknown> = {}
  ) {
    super(message);
    this.name = 'SpinApiError';
    this.code = code;
    this.httpStatus = httpStatus;
    this.details = details;
  }

  /** Stable logging surface for error boundaries + structured logs.
   *  Returns plain data (no `Error` prototype) so JSON.stringify round-
   *  trips cleanly in sentry/console/etc. */
  toJSON(): {
    code: string;
    message: string;
    httpStatus: number;
    details: Record<string, unknown>;
  } {
    return {
      code: this.code,
      message: this.message,
      httpStatus: this.httpStatus,
      details: this.details,
    };
  }
}

/** Narrow-ish parse of an unknown backend body into a `SpinError`-shaped
 *  object. Falls back to client-synthesized `bad_response` when the
 *  server returned a 4xx/5xx without the expected envelope. */
function parseErrorBody(
  body: unknown,
  httpStatus: number
): SpinApiError {
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>;
    const code = typeof b.code === 'string' ? b.code : 'bad_response';
    const message =
      typeof b.message === 'string' ? b.message : `HTTP ${httpStatus}`;
    const details =
      b.details && typeof b.details === 'object' && !Array.isArray(b.details)
        ? (b.details as Record<string, unknown>)
        : {};
    return new SpinApiError(code, message, httpStatus, details);
  }
  return new SpinApiError(
    'bad_response',
    `HTTP ${httpStatus} with non-JSON error body`,
    httpStatus
  );
}

async function readJsonOrThrow(
  response: Response,
  httpStatus: number
): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new SpinApiError(
      'bad_response',
      `HTTP ${httpStatus} body was not valid JSON`,
      httpStatus
    );
  }
}

/** Same as `readJsonOrThrow` but `postMarketplaceImportDraft` is documented to
 *  surface only `ImportDraftApiError` (plus success), never `SpinApiError`. */
async function readJsonOrImportDraftThrow(
  response: Response,
  httpStatus: number
): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ImportDraftApiError(
      'bad_response',
      `HTTP ${httpStatus} body was not valid JSON`,
      httpStatus,
      0
    );
  }
}

function isSpinResponse(value: unknown): value is SpinResponse {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.job_id === 'string' &&
    typeof v.realm_id === 'string' &&
    typeof v.phase === 'string' &&
    SPIN_PHASES.has(v.phase as SpinPhase) &&
    typeof v.adapter === 'string' &&
    typeof v.created_at === 'string' &&
    typeof v.status_url === 'string' &&
    typeof v.schema_version === 'number'
  );
}

function isSpinJob(value: unknown): value is SpinJob {
  if (!isSpinResponse(value)) return false;
  const v = value as unknown as Record<string, unknown>;
  return (
    typeof v.updated_at === 'string' &&
    typeof v.realm_description === 'string' &&
    typeof v.agent_count === 'number' &&
    v.outputs !== null &&
    typeof v.outputs === 'object' &&
    (v.error === null ||
      (typeof v.error === 'object' && v.error !== null))
  );
}

/** POST /realms/spin. Returns the parsed `SpinResponse` on 202. Throws
 *  `SpinApiError` on any other status or on network/parse failure. */
export async function postRealmSpin(
  base: string,
  body: SpinRequest,
  signal?: AbortSignal
): Promise<SpinResponse> {
  const url = `${base.replace(/\/+$/, '')}/realms/spin`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    throw new SpinApiError(
      'network_error',
      err instanceof Error ? err.message : 'fetch failed',
      0
    );
  }

  const status = response.status;
  const parsed = await readJsonOrThrow(response, status);

  if (status === 202) {
    if (!isSpinResponse(parsed)) {
      throw new SpinApiError(
        'bad_response',
        'POST /realms/spin 202 body missing required keys',
        status
      );
    }
    return parsed;
  }
  throw parseErrorBody(parsed, status);
}

/** GET /realms/{job_id}. Returns the parsed `SpinJob` on 200. Throws
 *  `SpinApiError` on any other status (404 → `code="job_not_found"`)
 *  or on network/parse failure. */
export async function getRealmJob(
  base: string,
  jobId: string,
  signal?: AbortSignal
): Promise<SpinJob> {
  const url = `${base.replace(/\/+$/, '')}/realms/${encodeURIComponent(
    jobId
  )}`;
  let response: Response;
  try {
    response = await fetch(url, { method: 'GET', signal });
  } catch (err) {
    throw new SpinApiError(
      'network_error',
      err instanceof Error ? err.message : 'fetch failed',
      0
    );
  }

  const status = response.status;
  const parsed = await readJsonOrThrow(response, status);

  if (status === 200) {
    if (!isSpinJob(parsed)) {
      throw new SpinApiError(
        'bad_response',
        'GET /realms/{job_id} 200 body missing required keys',
        status
      );
    }
    return parsed;
  }
  throw parseErrorBody(parsed, status);
}

/** DELETE /realms/{job_id}. Returns the parsed SpinJob on 202
 *  (destroy accepted; poll GET to observe completion). Returns null
 *  on 204 (idempotent no-op — already destroyed). Throws SpinApiError
 *  on any other status or on network/parse failure. */
export async function deleteRealmJob(
  base: string,
  jobId: string,
  signal?: AbortSignal
): Promise<SpinJob | null> {
  const url = `${base.replace(/\/+$/, '')}/realms/${encodeURIComponent(jobId)}`;
  let response: Response;
  try {
    response = await fetch(url, { method: 'DELETE', signal });
  } catch (err) {
    throw new SpinApiError(
      'network_error',
      err instanceof Error ? err.message : 'fetch failed',
      0
    );
  }

  const status = response.status;
  if (status === 204) {
    return null;
  }

  const parsed = await readJsonOrThrow(response, status);

  if (status === 202) {
    if (!isSpinJob(parsed)) {
      throw new SpinApiError(
        'bad_response',
        'DELETE /realms/{job_id} 202 body missing required keys',
        status
      );
    }
    return parsed;
  }
  throw parseErrorBody(parsed, status);
}

/** Story 7.2 — failures on `POST /marketplace/templates/import-draft`.
 *  Uses Core `{ code, detail }` (not `SpinError`). */
export class ImportDraftApiError extends Error {
  readonly code: string;
  readonly httpStatus: number;
  readonly schemaVersion: number;
  readonly detail: string;

  constructor(
    code: string,
    detail: string,
    httpStatus: number,
    schemaVersion: number
  ) {
    super(detail);
    this.name = 'ImportDraftApiError';
    this.code = code;
    this.detail = detail;
    this.httpStatus = httpStatus;
    this.schemaVersion = schemaVersion;
  }
}

function isMarketplaceImportDraftSuccess(
  value: unknown
): value is MarketplaceImportDraftSuccess {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  if (typeof v.schema_version !== 'number' || !v.draft || typeof v.draft !== 'object')
    return false;
  const d = v.draft as Record<string, unknown>;
  return (
    typeof d.agent_count === 'number' &&
    typeof d.realm_description === 'string' &&
    'adapter_hint' in d &&
    Array.isArray(d.policy_refs)
  );
}

/** POST /marketplace/templates/import-draft. Body must be the manifest JSON
 *  text (UTF-8). Verification runs only on Core — pass through bytes from
 *  `File.text()` without re-shaping. */
export async function postMarketplaceImportDraft(
  base: string,
  manifestJson: string,
  signal?: AbortSignal
): Promise<MarketplaceImportDraftSuccess> {
  const url = `${base.replace(/\/+$/, '')}/marketplace/templates/import-draft`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: manifestJson,
      signal,
    });
  } catch (err) {
    throw new ImportDraftApiError(
      'network_error',
      err instanceof Error ? err.message : 'fetch failed',
      0,
      0
    );
  }

  const status = response.status;
  const parsed = await readJsonOrImportDraftThrow(response, status);

  if (status === 200) {
    if (!isMarketplaceImportDraftSuccess(parsed)) {
      throw new ImportDraftApiError(
        'bad_response',
        'POST /marketplace/templates/import-draft 200 body missing required keys',
        status,
        0
      );
    }
    return parsed;
  }

  if (status === 422 && parsed && typeof parsed === 'object') {
    const b = parsed as Record<string, unknown>;
    const code = typeof b.code === 'string' ? b.code : 'bad_response';
    const det = typeof b.detail === 'string' ? b.detail : `HTTP ${status}`;
    const sv = typeof b.schema_version === 'number' ? b.schema_version : 0;
    throw new ImportDraftApiError(code, det, status, sv);
  }

  const fallback =
    parsed && typeof parsed === 'object' && 'detail' in parsed
      ? String((parsed as Record<string, unknown>).detail)
      : `HTTP ${status}`;
  throw new ImportDraftApiError('bad_response', fallback, status, 0);
}
