// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { Loader2, Sparkles } from 'lucide-react';
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

export function RealmToolbar({ className }: { className?: string }) {
  const description = useCanvasStore((s) => s.realmDescription);
  const setDescription = useCanvasStore((s) => s.setRealmDescription);
  const { phase, spinPrivateRealm, jobId } = useAwsSpin();

  return (
    <TooltipProvider>
      <header
        className={cn(
          'glass-panel relative z-20 flex flex-wrap items-center gap-3 border-b border-white/5 px-4 py-3 md:gap-4',
          className
        )}
      >
        <div className="flex items-center gap-2">
          <Sparkles className="size-5 text-realm-cyan" aria-hidden />
          <div>
            <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-realm-muted">
              Private Realm
            </p>
            <h1 className="text-sm font-semibold tracking-tight text-zinc-50 md:text-base">
              Command canvas
            </h1>
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
                  className="min-w-[9rem]"
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
