// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export type AgentCommsState = 'idle' | 'connecting' | 'live' | 'error';

export interface UseAgentCommsOptions {
  /** e.g. wss://realm.example/agents — wire when backend assigns realm */
  url?: string;
}

/**
 * Placeholder for encrypted agent messaging (WebSocket or gRPC-Web bridge).
 * Returns connection state + send; swap implementation when orchestration API lands.
 */
export function useAgentComms(opts: UseAgentCommsOptions = {}) {
  const { url } = opts;
  const wsRef = useRef<WebSocket | null>(null);
  const [state, setState] = useState<AgentCommsState>('idle');
  const [lastEvent, setLastEvent] = useState<string | null>(null);

  useEffect(() => {
    if (!url) {
      setState('idle');
      return;
    }
    setState('connecting');
    // Stub: real WebSocket opens here with TLS + binary frames as needed
    const id = window.setTimeout(() => setState('live'), 400);
    return () => {
      window.clearTimeout(id);
      wsRef.current?.close();
    };
  }, [url]);

  const sendEncrypted = useCallback((payload: Uint8Array | string) => {
    if (!url) {
      setLastEvent('queued (no transport URL)');
      return;
    }
    setLastEvent(typeof payload === 'string' ? `sent: ${payload.slice(0, 64)}` : `sent ${payload.byteLength} bytes`);
  }, [url]);

  return { state, lastEvent, sendEncrypted };
}
