// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export type DirijorRealtimeStatus =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'error';

export interface UseDirijorRealtimeOptions {
  /** wss://... from Dirijor Core after realm session (Epic 3). */
  url?: string;
  /** Realm / tenant id for subscribe/auth frames (stub reconnects when this changes). */
  realmId?: string;
}

/** Stub-only event kinds until Core wires onmessage → canvas (Epic 3). */
export type DirijorStubEventKind = 'topology' | 'metrics' | 'hitl';

/**
 * Placeholder transport for Dirijor Core → canvas (topology, metrics, HITL queue).
 * Replace with real WebSocket (or gRPC-Web) when Epic 3 APIs are available.
 */
export function useDirijorRealtime(opts: UseDirijorRealtimeOptions = {}) {
  const { url, realmId } = opts;
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<DirijorRealtimeStatus>('idle');
  const [lastMessageType, setLastMessageType] = useState<string | null>(null);

  useEffect(() => {
    if (!url) {
      setStatus('idle');
      setLastMessageType(null);
      return;
    }
    let cancelled = false;
    setLastMessageType(null);
    setStatus('connecting');
    // Stub: Epic 3 will open `url` scoped to `realmId` for subscribe/auth frames.
    const t = window.setTimeout(() => {
      if (!cancelled) setStatus('connected');
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [url, realmId]);

  const pushStubEvent = useCallback((type: DirijorStubEventKind) => {
    setLastMessageType(type);
  }, []);

  return {
    status,
    lastMessageType,
    /** Call when wiring real WS onmessage → Zustand/React Flow updates */
    pushStubEvent,
    realmId,
  };
}
