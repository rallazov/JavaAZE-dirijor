// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { ChevronDown, Loader2, PanelRight, PanelRightClose, RotateCcw, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useAwsSpin } from '@/hooks/useAwsSpin';
import { useCanvasStore } from '@/store/canvas-store';
import { cn } from '@/lib/utils';

const REALM_OPTIONS: { id: string; label: string; disabled?: boolean }[] = [
  { id: 'local', label: 'Private Realm (local)' },
  { id: '_soon', label: 'Additional realms…', disabled: true },
];

export function RealmToolbar({ className }: { className?: string }) {
  const description = useCanvasStore((s) => s.realmDescription);
  const setDescription = useCanvasStore((s) => s.setRealmDescription);
  const activeRealmId = useCanvasStore((s) => s.activeRealmId);
  const setActiveRealmId = useCanvasStore((s) => s.setActiveRealmId);
  const inspectorOpen = useCanvasStore((s) => s.inspectorOpen);
  const toggleInspector = useCanvasStore((s) => s.toggleInspector);
  const resetGraphToDemo = useCanvasStore((s) => s.resetGraphToDemo);
  const { phase, spinPrivateRealm, jobId } = useAwsSpin();

  return (
    <TooltipProvider>
      <header
        className={cn(
          'glass-panel relative z-20 flex flex-wrap items-center gap-3 border-b border-white/5 px-4 py-3 md:gap-4',
          className
        )}
      >
        <div className="flex items-center gap-1 md:gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0 text-realm-muted hover:text-realm-cyan"
                onClick={() => toggleInspector()}
                aria-expanded={inspectorOpen}
                aria-controls="realm-inspector"
                aria-label={inspectorOpen ? 'Hide inspector panel' : 'Show inspector panel'}
              >
                {inspectorOpen ? <PanelRightClose className="size-5" /> : <PanelRight className="size-5" />}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              {inspectorOpen ? 'Hide inspector' : 'Show inspector'}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0 text-realm-muted hover:text-amber-200/90"
                onClick={() => resetGraphToDemo()}
                aria-label="Reset canvas to demo graph and metrics"
              >
                <RotateCcw className="size-5" aria-hidden />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-xs">
              Reset canvas, metrics, and approval queue to the bundled demo (clears your realm description field).
            </TooltipContent>
          </Tooltip>
          <Sparkles className="size-5 text-realm-cyan" aria-hidden />
          <div>
            <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-realm-muted">
              Private Realm
            </p>
            <h1 className="text-sm font-semibold tracking-tight text-zinc-50 md:text-base">
              Command canvas
            </h1>
          </div>
          <div className="ml-1 flex items-center gap-1.5 border-l border-white/10 pl-2 md:ml-2 md:pl-3">
            <label className="sr-only" htmlFor="realm-switcher">
              Active realm
            </label>
            <span className="hidden text-[10px] font-mono uppercase tracking-wider text-realm-muted sm:inline">
              Realms
            </span>
            <div className="relative">
              <select
                id="realm-switcher"
                value={activeRealmId}
                onChange={(e) => setActiveRealmId(e.target.value)}
                title="Switch realm (stub: single active realm)"
                className={cn(
                  'h-9 max-w-[11rem] appearance-none rounded-lg border border-white/12 bg-black/45 py-1.5 pl-2.5 pr-8 text-xs font-medium text-zinc-100',
                  'outline-none ring-realm-cyan/25 transition-shadow duration-150 hover:border-realm-cyan/35 hover:shadow-glow-cyan',
                  'focus-visible:border-realm-cyan/45 focus-visible:ring-2'
                )}
                aria-describedby="realm-switcher-hint"
              >
                {REALM_OPTIONS.map((r) => (
                  <option key={r.id} value={r.id} disabled={r.disabled} title={r.disabled ? 'Coming soon' : undefined}>
                    {r.label}
                  </option>
                ))}
              </select>
              <ChevronDown
                className="pointer-events-none absolute right-2 top-1/2 size-4 -translate-y-1/2 text-realm-muted"
                aria-hidden
              />
            </div>
            <p id="realm-switcher-hint" className="sr-only">
              Multi-realm routing is a stub; only local demo realm is active today.
            </p>
          </div>
        </div>
        <p className="hidden max-w-md text-xs text-realm-muted md:block">
          Orchestrate isolated AWS-backed meshes, Harper policy, and encrypted agent traffic. Nothing
          leaves your boundary without verification.
        </p>
        <div className="ml-auto flex min-w-[min(100%,20rem)] flex-1 flex-wrap items-center justify-end gap-2 md:max-w-xl">
          <label className="sr-only" htmlFor="realm-desc">
            Describe your realm
          </label>
          <input
            id="realm-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe workloads, regions, compliance tier…"
            className="min-h-10 min-w-[12rem] flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-zinc-100 outline-none ring-realm-cyan/40 placeholder:text-realm-muted/80 focus:border-realm-cyan/40 focus:ring-2"
            autoComplete="off"
          />
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="inline-flex">
                <Button
                  type="button"
                  variant="primary"
                  size="default"
                  className="min-w-[9rem] transition-transform duration-150 active:scale-[0.98]"
                  disabled={phase === 'validating' || phase === 'provisioning'}
                  onClick={() => spinPrivateRealm({ realmDescription: description })}
                  aria-busy={phase === 'validating' || phase === 'provisioning'}
                >
                  {phase === 'idle' || phase === 'ready' || phase === 'failed' ? (
                    'Spin realm'
                  ) : (
                    <>
                      <Loader2 className="animate-spin" aria-hidden />
                      Spinning…
                    </>
                  )}
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-xs">
              Provisions private network segments and agent runtimes (stub — wire to AWS orchestration API).
            </TooltipContent>
          </Tooltip>
        </div>
        {jobId && phase === 'ready' && (
          <p className="basis-full text-right font-mono text-[10px] text-realm-emerald md:basis-auto" role="status">
            Job {jobId} · ready for mesh attach
          </p>
        )}
      </header>
    </TooltipProvider>
  );
}
