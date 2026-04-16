// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { Radio } from 'lucide-react';
import { useAgentComms } from '@/hooks/useAgentComms';
import { useCanvasStore } from '@/store/canvas-store';
import { cn } from '@/lib/utils';

export function StatusBar({ className }: { className?: string }) {
  const metrics = useCanvasStore((s) => s.metrics);
  const { state: comms } = useAgentComms({});

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
        <span className="text-zinc-200">{comms === 'live' ? 'Live stub' : 'Idle (set WSS URL)'}</span>
      </span>
      <span className="font-mono text-realm-muted">
        Median RTT{' '}
        <span className="text-realm-cyan">{metrics.latencyMs} ms</span>
      </span>
      <span className="font-mono text-realm-muted">
        Security posture{' '}
        <span className="text-realm-emerald">{metrics.securityPosture} / 100</span>
      </span>
      <span className="text-realm-muted">
        Audit trail signed · Harper policy engine · Human gates enforced on destructive actions
      </span>
    </footer>
  );
}
