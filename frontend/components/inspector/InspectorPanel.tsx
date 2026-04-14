// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { useMemo } from 'react';
import { FileKey2, Shield } from 'lucide-react';
import { HumanLoopGate } from '@/components/safety/HumanLoopGate';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { useHarperSecurity } from '@/hooks/useHarperSecurity';
import { useCanvasStore } from '@/store/canvas-store';
import { cn } from '@/lib/utils';
import type { AgentNodeData } from '@/types/agent';

export function InspectorPanel({ className }: { className?: string }) {
  const selectedId = useCanvasStore((s) => s.selectedNodeId);
  const nodes = useCanvasStore((s) => s.nodes);
  const metrics = useCanvasStore((s) => s.metrics);
  const pending = useCanvasStore((s) => s.pendingActions);
  const removePending = useCanvasStore((s) => s.removePending);
  const { verifyNode, getVerification } = useHarperSecurity();

  const agent = useMemo(
    () => nodes.find((n) => n.id === selectedId)?.data as AgentNodeData | undefined,
    [nodes, selectedId]
  );
  const verification = getVerification(selectedId);

  return (
    <aside
      className={cn(
        'glass-panel flex h-full min-h-0 w-full min-w-[min(100vw,24rem)] max-w-md flex-col border-l border-white/10 md:max-w-[420px]',
        className
      )}
      aria-label="Inspector and approvals"
    >
      <div className="border-b border-white/5 px-4 py-3">
        <h2 className="text-[10px] font-mono uppercase tracking-[0.25em] text-realm-muted">Inspector</h2>
        <p className="text-sm font-medium text-zinc-100">Node & safety context</p>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-6 p-4">
          <section aria-labelledby="sel-heading">
            <h3 id="sel-heading" className="mb-2 flex items-center gap-2 text-xs font-semibold text-zinc-200">
              <Shield className="size-4 text-realm-cyan" aria-hidden />
              Selection
            </h3>
            {agent ? (
              <div className="space-y-2 rounded-lg border border-white/10 bg-black/25 p-3 text-sm">
                <p className="font-semibold text-zinc-50">{agent.label}</p>
                <p className="font-mono text-xs text-realm-muted">
                  Role: {agent.role} · Safety: {(agent.safetyScore * 100).toFixed(1)}%
                </p>
                <button
                  type="button"
                  className="text-xs font-medium text-realm-cyan underline-offset-4 hover:underline"
                  onClick={() => {
                    if (selectedId) {
                      void verifyNode(selectedId);
                    }
                  }}
                >
                  Re-verify with Harper
                </button>
                {verification && (
                  <p className="font-mono text-[10px] text-realm-muted">
                    Last: {verification.fingerprint} @ {verification.checkedAt}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-xs text-realm-muted">
                Select an agent on the canvas. Keyboard: Tab moves focus between interactive controls; graph
                navigation uses pointer.
              </p>
            )}
          </section>

          <section aria-labelledby="realm-heading">
            <h3 id="realm-heading" className="mb-2 text-xs font-semibold text-zinc-200">
              Realm metrics
            </h3>
            <ul className="space-y-1 font-mono text-[11px] text-realm-muted">
              <li>
                Aggregate posture:{' '}
                <span className="text-realm-emerald">{metrics.securityPosture} / 100</span>
              </li>
              <li>
                Edge RTT p50: <span className="text-realm-cyan">{metrics.latencyMs} ms</span>
              </li>
            </ul>
          </section>

          <section aria-labelledby="audit-heading">
            <h3 id="audit-heading" className="mb-2 flex items-center gap-2 text-xs font-semibold text-zinc-200">
              <FileKey2 className="size-4 text-realm-emerald" aria-hidden />
              Audit preview
            </h3>
            <ul className="space-y-2">
              {metrics.auditPreview.map((row) => (
                <li
                  key={row.id}
                  className="rounded-md border border-white/5 bg-black/20 p-2 text-[11px] leading-snug text-realm-muted"
                >
                  <span className="font-mono text-[10px] text-realm-cyan">{row.at}</span> — {row.summary}
                </li>
              ))}
            </ul>
          </section>

          <Separator />

          <section aria-labelledby="hitl-heading">
            <h3 id="hitl-heading" className="mb-3 text-xs font-semibold text-zinc-200">
              Human in the loop
            </h3>
            <HumanLoopGate
              actions={pending}
              onApprove={(id) => removePending(id)}
              onReject={(id) => removePending(id)}
            />
          </section>
        </div>
      </ScrollArea>
    </aside>
  );
}
