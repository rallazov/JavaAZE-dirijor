// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';
//
// Thin React wrapper around `createRealtimeClient` (Story 3.3 AC 10).
//
// What belongs HERE: `useEffect` lifecycle, React state for `status`,
// StrictMode double-mount idempotency, forwarding events to the Zustand
// store actions (AC 4).
//
// What does NOT belong here: backoff math, URL building, reconnect/grace
// timers, runtime JSON parsing — those live in `lib/dirijor-realtime.ts`
// as pure functions + factory, and are unit-tested via Vitest.
//
// If you need to test this hook directly, land a jsdom + `mock-socket`
// harness story first (see Story 3.3 Dev Notes "Known follow-ups").

import { useEffect, useState } from 'react';
import { createRealtimeClient, buildWsUrl } from '@/lib/dirijor-realtime';
import { useCanvasStore } from '@/store/canvas-store';
import type {
  DirijorRealtimeEvent,
  DirijorRealtimeEventType,
  DirijorRealtimeStatus,
} from '@/types/realtime';

// Re-export for backward-compat with pre-3.3 import sites (only
// `CanvasShell.tsx` referenced the old export).
export type { DirijorRealtimeStatus } from '@/types/realtime';

/** @deprecated Story 3.3 replaced the stub enum with the full
 *  `DirijorRealtimeEventType` union. New code imports from
 *  `@/types/realtime` directly. */
export type DirijorStubEventKind = DirijorRealtimeEventType;

export interface UseDirijorRealtimeOptions {
  /** Fully-qualified base (e.g. `ws://127.0.0.1:8000/ws/realm`) — the hook
   *  appends `/{realmId}` via `buildWsUrl`. `undefined` keeps the hook in
   *  `idle` so the canvas demo path survives without a backend (AC 5). */
  url?: string;
  /** Realm / tenant id. Changes trigger a full reconnect (new URL → new
   *  `useEffect` invocation via the dependency array). */
  realmId?: string;
}

export interface UseDirijorRealtimeResult {
  status: DirijorRealtimeStatus;
  /** Last event `type` seen (useful for dev/StatusBar). `null` before first
   *  frame and when `status === 'idle'`. */
  lastMessageType: DirijorRealtimeEventType | null;
  realmId?: string;
}

/** Live Canvas ↔ Core transport. See `lib/dirijor-realtime.ts` for the
 *  factory contract and `types/realtime.ts` for the event union. */
export function useDirijorRealtime(
  opts: UseDirijorRealtimeOptions = {}
): UseDirijorRealtimeResult {
  const { url, realmId } = opts;
  const [status, setStatus] = useState<DirijorRealtimeStatus>('idle');
  const [lastMessageType, setLastMessageType] =
    useState<DirijorRealtimeEventType | null>(null);

  // Mirror the transport status into the Zustand store so `StatusBar` can
  // render the label without re-running the hook at every consumer (AC 4).
  const setRealtimeStatus = useCanvasStore((s) => s.setRealtimeStatus);
  useEffect(() => {
    setRealtimeStatus(status);
  }, [status, setRealtimeStatus]);

  useEffect(() => {
    const finalUrl = buildWsUrl(url, realmId);
    if (!finalUrl) {
      setStatus('idle');
      setLastMessageType(null);
      return;
    }

    setStatus('connecting');
    setLastMessageType(null);

    const client = createRealtimeClient({
      url: finalUrl,
      onStatus: (next) => {
        setStatus(next);
      },
      onEvent: (event: DirijorRealtimeEvent) => {
        setLastMessageType(event.type);
        const store = useCanvasStore.getState();
        switch (event.type) {
          case 'topology.delta':
            store.applyTopologyDelta(event.payload);
            break;
          case 'metrics.update':
            store.applyMetricsUpdate(event.payload);
            break;
          case 'hitl.pending':
            store.applyHitlPending(event.payload);
            break;
          case 'session.hello':
          case 'heartbeat':
          case 'session.bye':
            // hook-level concerns only — do NOT call store actions (AC 4).
            break;
          default: {
            // Exhaustiveness: adding a new event type fails to compile
            // until both the switch and the store reducer are updated.
            const _exhaustive: never = event;
            void _exhaustive;
          }
        }
      },
    });

    return () => {
      client.close();
    };
  }, [url, realmId]);

  return { status, lastMessageType, realmId };
}
