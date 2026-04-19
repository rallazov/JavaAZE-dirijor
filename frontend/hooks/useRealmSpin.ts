// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  DEFAULT_API_BASE,
  POLL_TIMEOUT_MS,
  SpinApiError,
  getRealmJob,
  postRealmSpin,
  resolveDirijorApiUrl,
} from '@/lib/dirijor-api';
import type { SpinJob, SpinPhase, SpinRequest } from '@/types/spin';

/** Backwards-compatible alias for Story 1.x consumers that imported
 *  `AwsSpinPhase` from `useAwsSpin.ts`. Deprecated — consume `SpinPhase`
 *  from `@/types/spin` in new code. Will be removed when the next
 *  cleanup story lands.
 *  @deprecated Use `SpinPhase` from `@/types/spin`. */
export type AwsSpinPhase = SpinPhase | 'idle';

const POLL_INTERVAL_MS = 750;

/** Central env-var resolver. The ONLY place in the app that reads
 *  `NEXT_PUBLIC_DIRIJOR_API_URL` — mirrors the Story 3.3 discipline for
 *  `NEXT_PUBLIC_DIRIJOR_WS_URL`. Kept as a callable so Next.js build-time
 *  inlining happens at the call site, not at module init. */
export function apiBase(): string {
  return resolveDirijorApiUrl(process.env.NEXT_PUBLIC_DIRIJOR_API_URL);
}

export interface SpinPrivateRealmArgs {
  realmDescription: string;
  adapterHint?: string;
  realmId?: string;
  agentCount?: number;
}

export interface UseRealmSpinState {
  phase: AwsSpinPhase;
  jobId: string | null;
  realmId: string | null;
  outputs: Record<string, unknown> | null;
  error: SpinApiError | null;
  spinPrivateRealm: (args: SpinPrivateRealmArgs) => Promise<void>;
  reset: () => void;
}

/** Client hook for the Story 2.1 realm-spin HTTP contract. Thin wrapper
 *  around the pure `dirijor-api` module — state + lifecycle only. No
 *  network logic, no URL building. */
export function useRealmSpin(): UseRealmSpinState {
  const [phase, setPhase] = useState<AwsSpinPhase>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [realmId, setRealmId] = useState<string | null>(null);
  const [outputs, setOutputs] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<SpinApiError | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeJobIdRef = useRef<string | null>(null);
  // Guard against overlapping polls when the interval callback runs
  // async work that outlives POLL_INTERVAL_MS (slow network, stalled
  // backend). Without this flag, every tick can spawn a new in-flight
  // fetch, racing state updates and leaking AbortControllers. This
  // stays in a ref (not state) so the next tick observes the flag
  // synchronously without re-rendering.
  const pollInFlightRef = useRef<boolean>(false);

  const clearTimers = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const abortInFlight = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const applyTerminalJob = useCallback((job: SpinJob) => {
    setPhase(job.phase);
    setOutputs(job.outputs ?? {});
    if (job.error) {
      // A terminal `failed` job surfaces its error envelope inside a
      // successful HTTP 200 body. Use `httpStatus=0` (the same sentinel
      // as `network_error` / `poll_timeout`) so downstream filters that
      // key on `httpStatus >= 400` do not mis-classify this as an HTTP
      // transport failure. Consumers that need to distinguish
      // on-the-wire HTTP errors from in-payload terminal errors can
      // key on `code` — backend codes never overlap with the
      // client-synthesized ones.
      const err = new SpinApiError(
        job.error.code,
        job.error.message,
        0,
        job.error.details ?? {}
      );
      setError(err);
      if (typeof console !== 'undefined' && console.warn) {
        try {
          console.warn(
            'useRealmSpin: terminal failed job job_id=%s code=%s message=%s',
            job.job_id,
            err.code,
            err.message
          );
        } catch {
          /* ignore */
        }
      }
    } else {
      setError(null);
    }
  }, []);

  const spinPrivateRealm = useCallback(
    async (args: SpinPrivateRealmArgs) => {
      clearTimers();
      abortInFlight();
      activeJobIdRef.current = null;
      pollInFlightRef.current = false;

      setError(null);
      setOutputs(null);
      setJobId(null);
      setRealmId(null);
      setPhase('validating');

      const base = apiBase();
      const body: SpinRequest = { realm_description: args.realmDescription };
      if (args.adapterHint) body.adapter_hint = args.adapterHint;
      if (args.realmId) body.realm_id = args.realmId;
      if (typeof args.agentCount === 'number')
        body.agent_count = args.agentCount;

      const controller = new AbortController();
      abortRef.current = controller;

      let accepted;
      try {
        accepted = await postRealmSpin(base, body, controller.signal);
      } catch (err) {
        if (err instanceof SpinApiError) {
          setError(err);
        } else if (err instanceof Error && err.name === 'AbortError') {
          return;
        } else {
          setError(
            new SpinApiError(
              'network_error',
              err instanceof Error ? err.message : 'unknown',
              0
            )
          );
        }
        setPhase('failed');
        return;
      }

      activeJobIdRef.current = accepted.job_id;
      setJobId(accepted.job_id);
      setRealmId(accepted.realm_id);
      setPhase(accepted.phase);

      const pollStart = Date.now();

      // TODO(2.x-or-6.3): replace this 750ms poll with a WebSocket push
      // subscription once the `realm.spin.phase` event type lands on
      // WS /ws/realm/{realm_id}. The backend broadcast_event() helper
      // already exists (Story 3.3) and only needs a new event_type
      // entry + a SCHEMA_VERSION bump 3 -> 4. Fixed-interval polling is
      // a deliberate v0.1 shortcut documented in Story 2.1 known follow-ups.
      intervalRef.current = setInterval(async () => {
        if (activeJobIdRef.current !== accepted.job_id) return;
        if (Date.now() - pollStart > POLL_TIMEOUT_MS) return;
        // Skip this tick if a previous poll is still in flight — a slow
        // network / stalled backend must not spawn overlapping fetches.
        if (pollInFlightRef.current) return;
        pollInFlightRef.current = true;
        const pollController = new AbortController();
        abortRef.current = pollController;
        try {
          const job = await getRealmJob(
            base,
            accepted.job_id,
            pollController.signal
          );
          if (activeJobIdRef.current !== accepted.job_id) return;
          if (job.phase === 'ready' || job.phase === 'failed') {
            clearTimers();
            applyTerminalJob(job);
            activeJobIdRef.current = null;
          } else {
            setPhase(job.phase);
          }
        } catch (err) {
          if (err instanceof Error && err.name === 'AbortError') return;
          if (activeJobIdRef.current !== accepted.job_id) return;
          if (err instanceof SpinApiError) {
            clearTimers();
            setError(err);
            setPhase('failed');
            activeJobIdRef.current = null;
          } else {
            // Defense-in-depth: `getRealmJob` SHOULD always throw
            // `SpinApiError`, but a future refactor (or a rare
            // non-Error throwable) must not leak into an unhandled
            // promise rejection that stalls the poll loop. Synthesize
            // a `bad_response` so the UI surfaces *something* and the
            // hook exits the loop cleanly.
            clearTimers();
            setError(
              new SpinApiError(
                'bad_response',
                err instanceof Error
                  ? `poll raised unexpected error: ${err.message}`
                  : 'poll raised non-Error throwable',
                0
              )
            );
            setPhase('failed');
            activeJobIdRef.current = null;
          }
        } finally {
          pollInFlightRef.current = false;
        }
      }, POLL_INTERVAL_MS);

      timeoutRef.current = setTimeout(() => {
        if (activeJobIdRef.current !== accepted.job_id) return;
        clearTimers();
        const timeoutErr = new SpinApiError(
          'poll_timeout',
          `realm spin did not reach a terminal phase within ${POLL_TIMEOUT_MS}ms`,
          0,
          { job_id: accepted.job_id }
        );
        if (typeof console !== 'undefined' && console.warn) {
          try {
            console.warn(
              'useRealmSpin: poll_timeout job_id=%s',
              accepted.job_id
            );
          } catch {
            /* ignore */
          }
        }
        setError(timeoutErr);
        setPhase('failed');
        activeJobIdRef.current = null;
      }, POLL_TIMEOUT_MS);
    },
    [abortInFlight, applyTerminalJob, clearTimers]
  );

  const reset = useCallback(() => {
    clearTimers();
    abortInFlight();
    activeJobIdRef.current = null;
    pollInFlightRef.current = false;
    setPhase('idle');
    setJobId(null);
    setRealmId(null);
    setOutputs(null);
    setError(null);
  }, [abortInFlight, clearTimers]);

  useEffect(() => {
    return () => {
      clearTimers();
      abortInFlight();
      activeJobIdRef.current = null;
      pollInFlightRef.current = false;
    };
  }, [abortInFlight, clearTimers]);

  return {
    phase,
    jobId,
    realmId,
    outputs,
    error,
    spinPrivateRealm,
    reset,
  };
}
