// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { FileKey2, Loader2, Shield } from 'lucide-react';
import { HumanLoopGate } from '@/components/safety/HumanLoopGate';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Button } from '@/components/ui/button';
import { useRealmToast } from '@/components/ui/realm-toast';
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
  const { toast } = useRealmToast();
  const [reverifying, setReverifying] = useState(false);
  const [hitlAnnouncement, setHitlAnnouncement] = useState('');
  const hitlSeqRef = useRef(0);
  const hitlClearTimerRef = useRef<number | null>(null);

  /**
   * Story 1.6 AC3 — polite announcement on HITL approve/reject.
   * Append an alternating trailing space so consecutive identical outcomes still mutate the
   * live region (screen readers skip identical text). Clear after a pause so the region
   * doesn't carry stale content across unrelated focus changes.
   */
  const announceHitl = useCallback((text: string) => {
    hitlSeqRef.current += 1;
    const padding = hitlSeqRef.current % 2 === 0 ? ' ' : '';
    setHitlAnnouncement(text + padding);
    if (hitlClearTimerRef.current !== null) {
      window.clearTimeout(hitlClearTimerRef.current);
    }
    hitlClearTimerRef.current = window.setTimeout(() => {
      setHitlAnnouncement('');
      hitlClearTimerRef.current = null;
    }, 4000);
  }, []);

  useEffect(() => {
    return () => {
      if (hitlClearTimerRef.current !== null) {
        window.clearTimeout(hitlClearTimerRef.current);
        hitlClearTimerRef.current = null;
      }
    };
  }, []);

  const agent = useMemo(
    () => nodes.find((n) => n.id === selectedId)?.data as AgentNodeData | undefined,
    [nodes, selectedId]
  );
  const verification = getVerification(selectedId);

  const runReverify = async () => {
    if (!selectedId) return;
    setReverifying(true);
    try {
      await verifyNode(selectedId);
      await new Promise((r) => setTimeout(r, 280));
      toast({
        title: 'Safety re-check complete',
        description: 'Harper attestation updated for this agent (stub — wire to Core verify API).',
        variant: 'success',
      });
    } catch {
      toast({
        title: 'Safety re-check failed',
        description: 'Harper could not refresh attestation for this agent.',
        variant: 'warn',
      });
    } finally {
      setReverifying(false);
    }
  };

  const onApproveHitl = useCallback(
    (id: string) => {
      const a = pending.find((p) => p.id === id);
      removePending(id);
      announceHitl(
        a ? `Approved: ${a.title}. Action removed from queue.` : 'Approved. Action removed from queue.'
      );
    },
    [pending, removePending, announceHitl]
  );

  const onRejectHitl = useCallback(
    (id: string) => {
      const a = pending.find((p) => p.id === id);
      removePending(id);
      announceHitl(
        a ? `Rejected: ${a.title}. Action removed from queue.` : 'Rejected. Action removed from queue.'
      );
    },
    [pending, removePending, announceHitl]
  );

  return (
    <div
      className={cn(
        'glass-panel flex h-full min-h-0 w-full min-w-[min(100vw,24rem)] max-w-md flex-col border-l border-white/10 md:max-w-[420px]',
        className
      )}
    >
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {hitlAnnouncement}
      </span>
      <div className="border-b border-white/5 px-4 py-3">
        <h2
          id="inspector-heading"
          tabIndex={-1}
          className="rounded text-[10px] font-mono uppercase tracking-[0.25em] text-realm-muted outline-none focus-visible:ring-2 focus-visible:ring-realm-cyan focus-visible:ring-offset-2 focus-visible:ring-offset-[hsl(222_47%_4%)]"
        >
          Inspector
        </h2>
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
              <div className="space-y-3 rounded-lg border border-white/10 bg-black/25 p-3 text-sm">
                <p className="font-semibold text-zinc-50">{agent.label}</p>
                <p className="font-mono text-xs text-realm-muted">
                  Role: {agent.role} · Safety: {(agent.safetyScore * 100).toFixed(1)}%
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="w-full"
                  disabled={reverifying}
                  aria-busy={reverifying}
                  onClick={() => void runReverify()}
                >
                  {reverifying ? (
                    <>
                      <Loader2 className="animate-spin" aria-hidden />
                      Re-verifying…
                    </>
                  ) : (
                    'Re-verify safety'
                  )}
                </Button>
                {verification ? (
                  <p className="font-mono text-[10px] text-realm-muted">
                    Last: {verification.fingerprint} @ {verification.checkedAt}
                  </p>
                ) : null}
              </div>
            ) : (
              <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-4 text-center text-sm text-realm-muted">
                Select an agent to inspect • Safety context appears here
              </div>
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
            <h3 id="hitl-heading" className="mb-3 text-xs font-semibold text-realm-amber">
              Human in the loop
            </h3>
            <HumanLoopGate actions={pending} onApprove={onApproveHitl} onReject={onRejectHitl} />
          </section>
        </div>
      </ScrollArea>
    </div>
  );
}
