// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
//
// Pure WebSocket client for the Canvas ↔ Core channel (Story 3.3).
//
// Design principles:
//   - No React, no DOM mutations, no `process.env` reads. Pure functions +
//     a factory that wraps a `WebSocket` instance. This lets us unit-test
//     backoff / URL building / retry policy without jsdom or mocks.
//   - `createRealtimeClient` owns the WebSocket, the reconnect timer, the
//     heartbeat-grace timer, and the attempt counter. It exposes a single
//     `close()` method (idempotent — safe in React 19 StrictMode).
//   - The hook (`useDirijorRealtime`) is a thin React wrapper that manages
//     `useEffect` lifecycle + React state. See `hooks/useDirijorRealtime.ts`.
//
// URL env-var convention: `process.env.NEXT_PUBLIC_DIRIJOR_WS_URL` is read
// ONLY by `components/canvas/CanvasShell.tsx` and passed through
// `resolveDirijorWsUrl()`. All other callers go through `buildWsUrl()`.

import type {
  DirijorRealtimeEvent,
  DirijorRealtimeStatus,
} from '@/types/realtime';

/** Cap on reconnect attempts. Past this, status flips to `error` and the
 *  client stops trying — manual refresh is required (operator intent). */
export const MAX_RECONNECT_ATTEMPTS = 8;

/** Client-side dead-connection grace. If we don't see ANY frame (heartbeat
 *  or otherwise) for `HEARTBEAT_GRACE_MULTIPLIER × heartbeat_interval_s`,
 *  we treat the connection as gone and enter the reconnect flow. */
export const HEARTBEAT_GRACE_MULTIPLIER = 2;

/** Fallback heartbeat interval used before `session.hello` arrives — matches
 *  the backend default so the first grace timer is never pathological. */
const DEFAULT_HEARTBEAT_INTERVAL_S = 15;

/** Normalize `process.env.NEXT_PUBLIC_DIRIJOR_WS_URL` into a well-formed
 *  base URL or `undefined`. An empty string MUST come back as `undefined` so
 *  the canvas keeps rendering in `npm run dev` without a backend (AC 5). */
export function resolveDirijorWsUrl(
  envVar: string | undefined
): string | undefined {
  if (envVar === undefined || envVar === null) return undefined;
  const trimmed = envVar.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

/** Compose the final per-realm URL. Trailing slashes on `base` are stripped.
 *  A missing realmId defaults to `"default"` (matches the back-end auth
 *  stub). Returns `undefined` when `base` is absent so callers can gate on
 *  a single `if (url === undefined)` instead of two. */
export function buildWsUrl(
  base: string | undefined,
  realmId: string | undefined
): string | undefined {
  if (!base) return undefined;
  const realm = (realmId ?? 'default').trim() || 'default';
  const trimmed = base.replace(/\/+$/, '');
  return `${trimmed}/${encodeURIComponent(realm)}`;
}

/** Exponential backoff with jitter — formula locked by Story 3.3 AC 6.
 *  Deterministic part: `min(30_000, 500 * 2^attempt)` ms.
 *  Jitter: `Math.random() * 500` ms (uniform in [0, 500)).
 *  Caller responsibility: call once per attempt, in order.
 */
export function computeBackoffMs(attempt: number): number {
  const n = Math.max(0, Math.floor(attempt));
  const exponential = Math.min(30_000, 500 * 2 ** n);
  const jitter = Math.floor(Math.random() * 500);
  return exponential + jitter;
}

/** Return `false` for client-fault close codes (terminal). The client MUST
 *  NOT retry on 4401 / 4403 — retrying wastes server resources and drowns
 *  logs. Every other code (1006 abnormal, 1011 server cleanup, 1000 clean,
 *  etc.) is retryable and the reconnect loop takes over. */
export function shouldRetryOnClose(code: number): boolean {
  if (code === 4401 || code === 4403) return false;
  return true;
}

export interface RealtimeClientOptions {
  /** Full WS URL including realm path (already composed by `buildWsUrl`). */
  url: string;
  /** Cadence hint for the client-side grace timer. Overridden per connection
   *  when `session.hello` arrives. */
  heartbeatIntervalS?: number;
  onEvent: (event: DirijorRealtimeEvent) => void;
  onStatus: (status: DirijorRealtimeStatus, detail?: string) => void;
}

export interface RealtimeClientHandle {
  /** Idempotent. Cancels any pending reconnect + heartbeat-grace timers
   *  and closes the underlying WebSocket if still open. */
  close(): void;
}

/** Narrow type-guard for inbound frames — keeps runtime parse errors from
 *  propagating into the store reducer. */
function isDirijorRealtimeEvent(value: unknown): value is DirijorRealtimeEvent {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  if (typeof v.type !== 'string') return false;
  if (typeof v.schema_version !== 'number') return false;
  if (typeof v.realm_id !== 'string') return false;
  if (typeof v.ts !== 'string') return false;
  if (typeof v.seq !== 'number') return false;
  if (!v.payload || typeof v.payload !== 'object') return false;
  return true;
}

/** Construct a managed WebSocket client. Not a React hook — the hook wraps
 *  this factory. `close()` is safe to call multiple times and from any
 *  lifecycle state (connecting, connected, reconnecting, closed). */
export function createRealtimeClient(
  opts: RealtimeClientOptions
): RealtimeClientHandle {
  const { url, onEvent, onStatus } = opts;
  let heartbeatIntervalS =
    opts.heartbeatIntervalS ?? DEFAULT_HEARTBEAT_INTERVAL_S;

  let disposed = false;
  let attempt = 0;
  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let graceTimer: ReturnType<typeof setTimeout> | null = null;

  const clearReconnectTimer = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };
  const clearGraceTimer = () => {
    if (graceTimer !== null) {
      clearTimeout(graceTimer);
      graceTimer = null;
    }
  };
  const armGraceTimer = () => {
    clearGraceTimer();
    const ms = HEARTBEAT_GRACE_MULTIPLIER * heartbeatIntervalS * 1000;
    graceTimer = setTimeout(() => {
      if (disposed) return;
      try {
        ws?.close(4000, 'heartbeat_grace_exceeded');
      } catch {
        // swallow — `onclose` handler drives the reconnect flow.
      }
    }, ms);
  };

  const scheduleReconnect = () => {
    if (disposed) return;
    if (attempt >= MAX_RECONNECT_ATTEMPTS) {
      logTerminal(
        'dirijor-realtime: giving up after %d attempts',
        MAX_RECONNECT_ATTEMPTS
      );
      onStatus('error', 'max_reconnect_attempts_exhausted');
      return;
    }
    const delay = computeBackoffMs(attempt);
    attempt += 1;
    onStatus('reconnecting', `attempt ${attempt}/${MAX_RECONNECT_ATTEMPTS}`);
    reconnectTimer = setTimeout(() => {
      if (disposed) return;
      open();
    }, delay);
  };

  const open = () => {
    if (disposed) return;
    clearReconnectTimer();
    onStatus('connecting');
    try {
      ws = new WebSocket(url);
    } catch (err) {
      // Constructing a WebSocket can throw synchronously on invalid URL.
      onStatus(
        'error',
        err instanceof Error ? err.message : 'ws_construct_failed'
      );
      return;
    }

    ws.onopen = () => {
      if (disposed) {
        try {
          ws?.close();
        } catch {
          /* ignore */
        }
        return;
      }
      onStatus('connected');
      armGraceTimer();
    };

    ws.onmessage = (ev: MessageEvent<string>) => {
      if (disposed) return;
      armGraceTimer();
      let parsed: unknown;
      try {
        parsed = JSON.parse(ev.data);
      } catch {
        return; // drop malformed frames silently; server shouldn't send them
      }
      if (!isDirijorRealtimeEvent(parsed)) return;

      if (parsed.type === 'session.hello') {
        attempt = 0; // reset on successful handshake (AC 6)
        const hinted = parsed.payload.heartbeat_interval_s;
        if (typeof hinted === 'number' && hinted > 0) {
          heartbeatIntervalS = hinted;
          armGraceTimer();
        }
      }

      try {
        onEvent(parsed);
      } catch (err) {
        // Never let a store reducer crash take down the transport. Dev
        // console gets the breadcrumb so the bug surfaces locally.
        if (typeof console !== 'undefined') {
          // eslint-disable-next-line no-console
          console.error('dirijor-realtime onEvent threw', err);
        }
      }
    };

    ws.onerror = () => {
      if (disposed) return;
      // `onerror` is typically followed by `onclose`; let the close handler
      // drive the reconnect so we don't double-schedule.
    };

    ws.onclose = (ev: CloseEvent) => {
      clearGraceTimer();
      if (disposed) return;
      if (!shouldRetryOnClose(ev.code)) {
        // AC 6 code-review patch — terminal closes (4401 / 4403) are
        // client-fault and NOT retried. Operators watching DevTools need
        // a breadcrumb with code + reason, not just a status flip. Gate
        // on `typeof console` so SSR / non-browser test environments
        // stay quiet (the Vitest `node` env has `console`, but being
        // defensive costs us nothing and future-proofs against workers).
        logTerminal(
          'dirijor-realtime: terminal WS close code=%d reason=%s',
          ev.code,
          ev.reason || '<none>'
        );
        onStatus(
          'error',
          ev.reason || `terminal_close_${ev.code}`
        );
        return;
      }
      scheduleReconnect();
    };
  };

  /** Dev-console breadcrumb helper. AC 6 requires operators see *why* the
   *  transport gave up (4401 / 4403 / max-attempts) without decoding a
   *  `status === 'error'` flip. Written via `console.warn` so it shows up
   *  in default DevTools filters but does not trip error-boundary
   *  reporters. First arg is a printf-style format so browser DevTools
   *  formats it as a single collapsible log entry. */
  function logTerminal(fmt: string, ...args: unknown[]): void {
    if (typeof console === 'undefined' || !console.warn) return;
    try {
      console.warn(fmt, ...args);
    } catch {
      // ignore — a broken console must never take down the transport.
    }
  }

  open();

  return {
    close(): void {
      if (disposed) return;
      disposed = true;
      clearReconnectTimer();
      clearGraceTimer();
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
      ws = null;
    },
  };
}
