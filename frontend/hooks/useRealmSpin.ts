// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  POLL_TIMEOUT_MS,
  SpinApiError,
  deleteRealmJob,
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
  destroying: boolean;
  destroyed: boolean;
  spinPrivateRealm: (args: SpinPrivateRealmArgs) => Promise<void>;
  destroyPrivateRealm: () => Promise<void>;
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
  const [destroying, setDestroying] = useState(false);
  const [destroyed, setDestroyed] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const destroyIntervalRef = useRef<ReturnType<typeof setInterval> | null>(
    null
  );
  const destroyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeJobIdRef = useRef<string | null>(null);
  // Guard against overlapping polls when the interval callback runs
  // async work that outlives POLL_INTERVAL_MS (slow network, stalled
  // backend). Without this flag, every tick can spawn a new in-flight
  // fetch, racing state updates and leaking AbortControllers. This
  // stays in a ref (not state) so the next tick observes the flag
  // synchronously without re-rendering.
  const pollInFlightRef = useRef<boolean>(false);
  const destroyPollInFlightRef = useRef<boolean>(false);

  const clearTimers = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (destroyIntervalRef.current !== null) {
      clearInterval(destroyIntervalRef.current);
      destroyIntervalRef.current = null;
    }
    if (destroyTimeoutRef.current !== null) {
      clearTimeout(destroyTimeoutRef.current);
      destroyTimeoutRef.current = null;
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
      destroyPollInFlightRef.current = false;

      setError(null);
      setOutputs(null);
      setJobId(null);
      setRealmId(null);
      setPhase('validating');
      setDestroyed(false);
      setDestroying(false);

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
      // entry + a future SCHEMA_VERSION bump (e.g. 4 -> 5) when push-based
      // realm.spin.phase ships. Fixed-interval polling is a deliberate v0.1
      // shortcut documented in Story 2.1 known follow-ups.
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

  const destroyPrivateRealm = useCallback(async () => {
    if (phase !== 'ready' || jobId === null) {
      if (typeof console !== 'undefined' && console.warn) {
        console.warn(
          'useRealmSpin: destroyPrivateRealm ignored (need phase=ready and jobId)'
        );
      }
      return;
    }

    const base = apiBase();
    const targetJobId = jobId;

    if (destroyIntervalRef.current !== null) {
      clearInterval(destroyIntervalRef.current);
      destroyIntervalRef.current = null;
    }
    if (destroyTimeoutRef.current !== null) {
      clearTimeout(destroyTimeoutRef.current);
      destroyTimeoutRef.current = null;
    }

    setDestroying(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const accepted = await deleteRealmJob(
        base,
        targetJobId,
        controller.signal
      );

      if (accepted === null) {
        setDestroying(false);
        setDestroyed(true);
        try {
          const j = await getRealmJob(base, targetJobId, controller.signal);
          setOutputs((j.outputs ?? {}) as Record<string, unknown>);
        } catch {
          setOutputs({ destroyed: true });
        }
        return;
      }

      const pollStart = Date.now();

      // TODO(2.x-or-6.3): replace this 750ms poll with a WebSocket push
      // subscription once the `realm.spin.phase` event type lands on
      // WS /ws/realm/{realm_id}. The backend broadcast_event() helper
      // already exists (Story 3.3) and only needs a new event_type
      // entry + a future SCHEMA_VERSION bump (e.g. 4 -> 5) when push-based
      // realm.spin.phase ships. Fixed-interval polling is a deliberate v0.1
      // shortcut documented in Story 2.1 known follow-ups.
      destroyIntervalRef.current = setInterval(async () => {
        if (Date.now() - pollStart > POLL_TIMEOUT_MS) return;
        if (destroyPollInFlightRef.current) return;
        destroyPollInFlightRef.current = true;
        const pollController = new AbortController();
        abortRef.current = pollController;
        try {
          const job = await getRealmJob(
            base,
            targetJobId,
            pollController.signal
          );
          const out = job.outputs ?? {};
          if (out.destroyed === true) {
            if (destroyIntervalRef.current !== null) {
              clearInterval(destroyIntervalRef.current);
              destroyIntervalRef.current = null;
            }
            if (destroyTimeoutRef.current !== null) {
              clearTimeout(destroyTimeoutRef.current);
              destroyTimeoutRef.current = null;
            }
            setOutputs(out as Record<string, unknown>);
            setDestroying(false);
            setDestroyed(true);
            return;
          }
          if (out.destroy_error != null) {
            if (typeof out.destroy_error !== 'object') {
              if (destroyIntervalRef.current !== null) {
                clearInterval(destroyIntervalRef.current);
                destroyIntervalRef.current = null;
              }
              if (destroyTimeoutRef.current !== null) {
                clearTimeout(destroyTimeoutRef.current);
                destroyTimeoutRef.current = null;
              }
              setDestroying(false);
              setError(
                new SpinApiError(
                  'bad_response',
                  'outputs.destroy_error has unexpected shape',
                  0
                )
              );
              return;
            }
            const d = out.destroy_error as {
              code?: string;
              message?: string;
              details?: Record<string, unknown>;
            };
            if (destroyIntervalRef.current !== null) {
              clearInterval(destroyIntervalRef.current);
              destroyIntervalRef.current = null;
            }
            if (destroyTimeoutRef.current !== null) {
              clearTimeout(destroyTimeoutRef.current);
              destroyTimeoutRef.current = null;
            }
            setDestroying(false);
            setError(
              new SpinApiError(
                typeof d.code === 'string' ? d.code : 'terraform_destroy_failed',
                typeof d.message === 'string' ? d.message : 'destroy failed',
                0,
                d.details ?? {}
              )
            );
          }
        } catch (err) {
          if (err instanceof Error && err.name === 'AbortError') return;
          if (destroyIntervalRef.current !== null) {
            clearInterval(destroyIntervalRef.current);
            destroyIntervalRef.current = null;
          }
          if (destroyTimeoutRef.current !== null) {
            clearTimeout(destroyTimeoutRef.current);
            destroyTimeoutRef.current = null;
          }
          if (err instanceof SpinApiError) {
            setDestroying(false);
            setError(err);
          } else {
            setDestroying(false);
            setError(
              new SpinApiError(
                'bad_response',
                err instanceof Error
                  ? `destroy poll raised unexpected error: ${err.message}`
                  : 'destroy poll raised non-Error throwable',
                0
              )
            );
          }
        } finally {
          destroyPollInFlightRef.current = false;
        }
      }, POLL_INTERVAL_MS);

      destroyTimeoutRef.current = setTimeout(() => {
        if (destroyIntervalRef.current !== null) {
          clearInterval(destroyIntervalRef.current);
          destroyIntervalRef.current = null;
        }
        destroyTimeoutRef.current = null;
        const timeoutErr = new SpinApiError(
          'poll_timeout',
          `realm destroy did not finish within ${POLL_TIMEOUT_MS}ms`,
          0,
          { job_id: targetJobId }
        );
        if (typeof console !== 'undefined' && console.warn) {
          try {
            console.warn(
              'useRealmSpin: destroy poll_timeout job_id=%s',
              targetJobId
            );
          } catch {
            /* ignore */
          }
        }
        setDestroying(false);
        setError(timeoutErr);
      }, POLL_TIMEOUT_MS);
    } catch (err) {
      setDestroying(false);
      if (err instanceof Error && err.name === 'AbortError') return;
      if (err instanceof SpinApiError) {
        setError(err);
      } else {
        setError(
          new SpinApiError(
            'network_error',
            err instanceof Error ? err.message : 'unknown',
            0
          )
        );
      }
    }
  }, [phase, jobId]);

  const reset = useCallback(() => {
    clearTimers();
    abortInFlight();
    activeJobIdRef.current = null;
    pollInFlightRef.current = false;
    destroyPollInFlightRef.current = false;
    setPhase('idle');
    setJobId(null);
    setRealmId(null);
    setOutputs(null);
    setError(null);
    setDestroyed(false);
    setDestroying(false);
  }, [abortInFlight, clearTimers]);

  useEffect(() => {
    return () => {
      clearTimers();
      abortInFlight();
      activeJobIdRef.current = null;
      pollInFlightRef.current = false;
      destroyPollInFlightRef.current = false;
    };
  }, [abortInFlight, clearTimers]);

  return {
    phase,
    jobId,
    realmId,
    outputs,
    error,
    destroying,
    destroyed,
    spinPrivateRealm,
    destroyPrivateRealm,
    reset,
  };
}
