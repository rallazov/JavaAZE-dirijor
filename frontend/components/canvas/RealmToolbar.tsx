// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, FileUp, Loader2, PanelRight, PanelRightClose, RotateCcw, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { apiBase, useRealmSpin } from '@/hooks/useRealmSpin';
import { ImportDraftApiError, postMarketplaceImportDraft } from '@/lib/dirijor-api';
import { useCanvasStore } from '@/store/canvas-store';
import { cn } from '@/lib/utils';

const REALM_OPTIONS: { id: string; label: string; disabled?: boolean }[] = [
  { id: 'local', label: 'Private Realm (local)' },
  { id: '_soon', label: 'Additional realms…', disabled: true },
];

/** Reject before `file.text()` to match Core's import body cap without large tab allocations. */
const MAX_IMPORT_TEMPLATE_FILE_BYTES = 2 * 1024 * 1024;
const IMPORT_DRAFT_TIMEOUT_MS = 15_000;

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function RealmToolbar({ className }: { className?: string }) {
  const description = useCanvasStore((s) => s.realmDescription);
  const setDescription = useCanvasStore((s) => s.setRealmDescription);
  const activeRealmId = useCanvasStore((s) => s.activeRealmId);
  const setActiveRealmId = useCanvasStore((s) => s.setActiveRealmId);
  const inspectorOpen = useCanvasStore((s) => s.inspectorOpen);
  const toggleInspector = useCanvasStore((s) => s.toggleInspector);
  const resetGraphToDemo = useCanvasStore((s) => s.resetGraphToDemo);
  const {
    phase,
    spinPrivateRealm,
    destroyPrivateRealm,
    jobId,
    realmId,
    error,
    destroying,
    destroyed,
    outputs,
  } = useRealmSpin();

  const [destroyArmed, setDestroyArmed] = useState(false);
  const importInputRef = useRef<HTMLInputElement>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState<ImportDraftApiError | null>(null);
  const [prefillAdapterHint, setPrefillAdapterHint] = useState<string | undefined>(undefined);
  const [prefillAgentCount, setPrefillAgentCount] = useState<number | undefined>(undefined);

  const busySpin = phase === 'validating' || phase === 'provisioning';

  useEffect(() => {
    if (!destroyArmed) return;
    const id = setTimeout(() => setDestroyArmed(false), 3000);
    return () => clearTimeout(id);
  }, [destroyArmed]);

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
                id="inspector-toggle-btn"
                onClick={() => toggleInspector('toolbar')}
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
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            className="sr-only"
            aria-label="Import marketplace template JSON file"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              e.target.value = '';
              if (!file) return;
              setImportError(null);
              if (file.size > MAX_IMPORT_TEMPLATE_FILE_BYTES) {
                setImportError(
                  new ImportDraftApiError(
                    'import_file_too_large',
                    `Template file is ${formatBytes(file.size)}; maximum is ${formatBytes(
                      MAX_IMPORT_TEMPLATE_FILE_BYTES
                    )} before import.`,
                    0,
                    0
                  )
                );
                return;
              }
              setImportBusy(true);
              const controller = new AbortController();
              const timeoutId = window.setTimeout(
                () => controller.abort(),
                IMPORT_DRAFT_TIMEOUT_MS
              );
              try {
                const text = await file.text();
                const res = await postMarketplaceImportDraft(
                  apiBase(),
                  text,
                  controller.signal
                );
                setDescription(res.draft.realm_description);
                setPrefillAdapterHint(res.draft.adapter_hint ?? undefined);
                setPrefillAgentCount(res.draft.agent_count);
              } catch (err) {
                setPrefillAdapterHint(undefined);
                setPrefillAgentCount(undefined);
                if (err instanceof ImportDraftApiError) {
                  setImportError(err);
                } else {
                  setImportError(
                    new ImportDraftApiError(
                      'bad_response',
                      err instanceof Error ? err.message : 'import failed',
                      0,
                      0
                    )
                  );
                }
              } finally {
                window.clearTimeout(timeoutId);
                setImportBusy(false);
              }
            }}
          />
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="inline-flex">
                <Button
                  type="button"
                  variant="outline"
                  size="default"
                  className="min-w-[8rem] gap-1.5"
                  disabled={importBusy || busySpin}
                  aria-busy={importBusy}
                  onClick={() => importInputRef.current?.click()}
                >
                  {importBusy ? (
                    <>
                      <Loader2 className="size-4 animate-spin" aria-hidden />
                      Importing…
                    </>
                  ) : (
                    <>
                      <FileUp className="size-4" aria-hidden />
                      Import template
                    </>
                  )}
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-xs">
              Upload a verified template `.json` — Core validates and prefills the realm description
              for POST /realms/spin.
            </TooltipContent>
          </Tooltip>
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
                  disabled={busySpin}
                  onClick={() =>
                    spinPrivateRealm({
                      realmDescription: description,
                      adapterHint: prefillAdapterHint,
                      agentCount: prefillAgentCount,
                    })
                  }
                  aria-busy={busySpin}
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
              Calls POST /realms/spin on Dirijor Core (Story 2.1).
            </TooltipContent>
          </Tooltip>
        </div>
        {jobId && phase === 'ready' && !destroyed && (
          <div className="basis-full flex flex-wrap items-center justify-end gap-2 md:basis-auto">
            <p className="text-right font-mono text-[10px] text-realm-emerald">
              Job {jobId} · realm {realmId ?? '—'} · ready for mesh attach
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="shrink-0 border-white/15 text-xs text-zinc-400 hover:text-zinc-200"
              disabled={destroying}
              aria-busy={destroying}
              onClick={() => {
                if (destroyArmed) {
                  setDestroyArmed(false);
                  void destroyPrivateRealm();
                  return;
                }
                setDestroyArmed(true);
              }}
            >
              {destroying ? (
                <>
                  <Loader2 className="mr-1 inline size-3.5 animate-spin" aria-hidden />
                  Destroying…
                </>
              ) : destroyArmed ? (
                'Click again to destroy'
              ) : (
                'Destroy realm'
              )}
            </Button>
          </div>
        )}
        {jobId && phase === 'ready' && destroyed && (
          <p
            className="basis-full text-right font-mono text-[10px] text-realm-muted md:basis-auto"
            role="status"
          >
            Realm {realmId ?? '—'} destroyed (
            {typeof outputs?.destroyed_at === 'string'
              ? outputs.destroyed_at
              : '—'}
            ). Job {jobId} retained for audit.
          </p>
        )}
        {importError && (
          <p
            className="basis-full text-right font-mono text-[10px] text-amber-300 md:basis-auto"
            role="status"
          >
            import {importError.code}: {importError.detail}
          </p>
        )}
        {phase === 'failed' && error && (
          <p
            className="basis-full text-right font-mono text-[10px] text-amber-300 md:basis-auto"
            role="status"
          >
            {error.code}: {error.message}
          </p>
        )}
      </header>
    </TooltipProvider>
  );
}
