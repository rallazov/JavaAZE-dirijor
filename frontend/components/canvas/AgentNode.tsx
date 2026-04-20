// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import { Activity, Fingerprint } from 'lucide-react';
import { SafetyBadge } from '@/components/safety/SafetyBadge';
import {
  getSafetyScoreTier,
  safetyTierOuterPulseClass,
  safetyTierProgressStrokeClass,
  safetyTierTextClass,
} from '@/lib/safety-visual';
import { cn } from '@/lib/utils';
import type { AgentNodeData } from '@/types/agent';

const ringClass: Record<AgentNodeData['status'], string> = {
  healthy: 'border-realm-cyan shadow-glow-cyan',
  degraded: 'border-realm-amber shadow-glow-amber',
  critical: 'border-realm-crimson shadow-glow-crimson animate-pulse',
  pending: 'border-realm-muted',
  quarantined:
    'border-violet-500 shadow-[0_0_18px_rgba(139,92,246,0.45)] ring-1 ring-violet-400/70',
};

/** Badge = qualitative AgentStatus; score ring = quantitative safetyScore (95+ / 80–94 / &lt;80). */
function AgentNodeInner({ data, selected }: NodeProps<AgentNodeData>) {
  const pct = Math.round(data.safetyScore * 100);
  const tier = getSafetyScoreTier(data.safetyScore);

  const tierConic =
    tier === 'high'
      ? 'from_180deg_at_50%_50%,hsl(var(--realm-cyan)/0.14),transparent_62%'
      : tier === 'mid'
        ? 'from_180deg_at_50%_50%,hsl(var(--realm-amber)/0.12),transparent_62%'
        : 'from_180deg_at_50%_50%,hsl(var(--realm-crimson)/0.11),transparent_62%';

  return (
    <div
      className={cn(
        'relative min-w-[200px] rounded-xl border-2 bg-realm-glass/90 p-3 backdrop-blur-xl transition-transform duration-200',
        ringClass[data.status],
        selected && 'scale-[1.02] ring-2 ring-realm-cyan/60 ring-offset-2 ring-offset-[hsl(222_47%_4%)]'
      )}
      role="group"
      aria-label={`${data.label}, safety ${pct} percent`}
    >
      <div
        className={cn(
          'pointer-events-none absolute inset-0 rounded-xl opacity-50',
          `bg-[conic-gradient(${tierConic})]`,
          tier === 'high' && 'animate-safety-pulse-fast',
          tier === 'mid' && 'animate-safety-pulse-medium',
          tier === 'low' && 'animate-safety-pulse-slow'
        )}
      />
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2.5 !w-2.5 !border-2 !border-realm-cyan/80 !bg-zinc-950"
        aria-label="Ingress"
      />
      <div className="relative flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-widest text-realm-muted">Agent</p>
          <p className="text-sm font-semibold text-zinc-50">{data.label}</p>
        </div>
        <SafetyBadge status={data.status} />
      </div>
      <div className="relative mt-3 flex items-center gap-3">
        <div
          className="relative grid size-[52px] shrink-0 place-items-center rounded-full border border-white/10"
          aria-hidden
        >
          <svg className="absolute size-[52px] -rotate-90" viewBox="0 0 36 36">
            <circle cx="18" cy="18" r="15.5" fill="none" className="stroke-white/10" strokeWidth="3" />
            <circle
              cx="18"
              cy="18"
              r="17.5"
              fill="none"
              strokeWidth="1.25"
              className={cn('fill-none', safetyTierOuterPulseClass[tier])}
              pathLength={100}
            />
            <circle
              cx="18"
              cy="18"
              r="15.5"
              fill="none"
              className={cn(
                'transition-[stroke-dashoffset] duration-500',
                safetyTierProgressStrokeClass[tier]
              )}
              strokeWidth="3"
              strokeDasharray={`${pct} ${100 - pct}`}
              pathLength={100}
            />
          </svg>
          <span
            className={cn(
              'relative font-mono text-[10px] font-semibold tabular-nums',
              safetyTierTextClass[tier]
            )}
          >
            {pct}
          </span>
        </div>
        <div className="min-w-0 flex-1 space-y-1 text-xs text-realm-muted">
          <p className="flex items-center gap-1">
            <Activity className="size-3.5 text-realm-cyan" aria-hidden />
            <span className="font-mono text-zinc-300">
              {data.latencyMs != null ? `${data.latencyMs} ms RTT` : '— latency'}
            </span>
          </p>
          <p className="flex items-start gap-1 truncate">
            <Fingerprint className="mt-0.5 size-3.5 shrink-0 text-realm-cyan/90" aria-hidden />
            <span className="truncate" title={data.signaturePreview}>
              {data.signaturePreview ?? 'Unsigned preview'}
            </span>
          </p>
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2.5 !w-2.5 !border-2 !border-realm-emerald/80 !bg-zinc-950"
        aria-label="Egress"
      />
    </div>
  );
}

export const AgentNode = memo(AgentNodeInner);
