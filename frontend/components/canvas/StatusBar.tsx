// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { Radio } from 'lucide-react';
import { useAgentComms } from '@/hooks/useAgentComms';
import { useCanvasStore } from '@/store/canvas-store';
import { cn } from '@/lib/utils';
import type { DirijorRealtimeStatus } from '@/types/realtime';

/** Story 3.3 AC 4 — transport label mapping. Kept as a pure function so we
 *  can unit-test it later if the label text changes. */
function realtimeLabel(status: DirijorRealtimeStatus): string {
  switch (status) {
    case 'connected':
      return 'Live';
    case 'connecting':
      return 'Connecting…';
    case 'reconnecting':
      return 'Reconnecting…';
    case 'error':
      return 'Disconnected';
    case 'idle':
    default:
      return 'Idle (set NEXT_PUBLIC_DIRIJOR_WS_URL)';
  }
}

export function StatusBar({ className }: { className?: string }) {
  const metrics = useCanvasStore((s) => s.metrics);
  const realtimeStatus = useCanvasStore((s) => s.realtimeStatus);
  // Story 3.3 AC 4 — `useAgentComms` is a separate (pre-3.3) transport stub
  // that will be cleaned up in a future story. We keep reading it so its
  // behavior stays observable, but the primary label now reflects the real
  // Dirijor Core WebSocket status.
  const { state: _legacyComms } = useAgentComms({});
  void _legacyComms;

  return (
    <footer
      className={cn(
        'glass-panel flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-white/5 px-4 py-2 text-xs',
        className
      )}
      role="status"
      aria-live="polite"
      aria-label="Realm status and metrics"
    >
      <span className="flex items-center gap-2 font-mono text-realm-muted">
        <Radio className="size-3.5 text-realm-cyan" aria-hidden />
        Transport
        <span className="text-zinc-200">{realtimeLabel(realtimeStatus)}</span>
      </span>
      <span className="font-mono text-realm-muted">
        Median RTT{' '}
        <span className="text-realm-cyan">{metrics.latencyMs} ms</span>
      </span>
      <span className="font-mono text-realm-muted">
        Security posture{' '}
        <span className="text-realm-emerald">{metrics.securityPosture} / 100</span>
      </span>
      <span className="font-mono text-realm-muted">
        Quarantined agents{' '}
        <span className="text-realm-amber">{metrics.quarantinedAgentCount}</span>
      </span>
      <span className="text-realm-muted">
        Audit trail signed · Harper policy engine · Human gates enforced on destructive actions
      </span>
    </footer>
  );
}
