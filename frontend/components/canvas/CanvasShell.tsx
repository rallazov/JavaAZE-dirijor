// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  type Node,
  type Edge,
} from 'reactflow';
import { PanelRight } from 'lucide-react';
import { AgentNode } from '@/components/canvas/AgentNode';
import { AnimatedEdge } from '@/components/canvas/AnimatedEdge';
import { InspectorPanel } from '@/components/inspector/InspectorPanel';
import { RealmToolbar } from '@/components/canvas/RealmToolbar';
import { StatusBar } from '@/components/canvas/StatusBar';
import { Button } from '@/components/ui/button';
import { RealmToastProvider } from '@/components/ui/realm-toast';
import { useDirijorRealtime } from '@/hooks/useDirijorRealtime';
import { resolveDirijorWsUrl } from '@/lib/dirijor-realtime';
import { scoreToMinimapColor } from '@/lib/safety-visual';
import { useCanvasStore, REALM_NODE_EXTENT, REALM_TRANSLATE_EXTENT } from '@/store/canvas-store';
import type { AgentNodeData } from '@/types/agent';
import { cn } from '@/lib/utils';
import 'reactflow/dist/style.css';

const nodeTypes = { agent: AgentNode };
const edgeTypes = { encrypted: AnimatedEdge };

export function CanvasShell() {
  return (
    <RealmToastProvider>
      <CanvasShellInner />
    </RealmToastProvider>
  );
}

function CanvasShellInner() {
  const nodes = useCanvasStore((s) => s.nodes) as Node<AgentNodeData>[];
  const edges = useCanvasStore((s) => s.edges) as Edge[];
  const onNodesChange = useCanvasStore((s) => s.onNodesChange);
  const onEdgesChange = useCanvasStore((s) => s.onEdgesChange);
  const onConnect = useCanvasStore((s) => s.onConnect);
  const selectNode = useCanvasStore((s) => s.selectNode);
  const selectedId = useCanvasStore((s) => s.selectedNodeId);
  const inspectorOpen = useCanvasStore((s) => s.inspectorOpen);
  const inspectorFocusReturn = useCanvasStore((s) => s.inspectorFocusReturn);
  const setInspectorOpen = useCanvasStore((s) => s.setInspectorOpen);
  const activeRealmId = useCanvasStore((s) => s.activeRealmId);

  /** Story 3.3 — live WebSocket transport. `NEXT_PUBLIC_DIRIJOR_WS_URL`
   *  is the ONLY env-var read site; all other callers flow through
   *  `resolveDirijorWsUrl` / `buildWsUrl` (see `lib/dirijor-realtime.ts`).
   *  When the env var is unset, the hook stays `idle` so the demo canvas
   *  keeps rendering in `npm run dev` without a backend (AC 5). */
  useDirijorRealtime({
    url: resolveDirijorWsUrl(process.env.NEXT_PUBLIC_DIRIJOR_WS_URL),
    realmId: activeRealmId,
  });

  const [live, setLive] = useState('');

  useEffect(() => {
    if (!selectedId) {
      setLive('Nothing selected. Choose an agent node to inspect policy and signatures.');
      return;
    }
    const n = nodes.find((x) => x.id === selectedId);
    setLive(n ? `${n.data.label} selected. Safety ${(n.data.safetyScore * 100).toFixed(0)} percent.` : '');
  }, [selectedId, nodes]);

  const onNodeClick = useCallback(
    (_: MouseEvent, node: Node<AgentNodeData>) => {
      selectNode(node.id);
    },
    [selectNode]
  );

  const defaultEdgeOptions = useMemo(() => ({ type: 'encrypted' as const }), []);

  const prevInspectorOpen = useRef<boolean | null>(null);
  const focusRafRef = useRef<number | null>(null);

  /**
   * Story 1.6 — focus inspector title when panel opens; restore opener on close.
   * Skip initial mount (don't steal focus if inspector is default-open).
   * Cancel any pending rAF so rapid toggles don't race competing focus targets.
   * For close: if preferred return target is hidden (e.g. FAB on desktop), fall back to toolbar toggle.
   */
  useEffect(() => {
    const prev = prevInspectorOpen.current;
    if (prev === null) {
      prevInspectorOpen.current = inspectorOpen;
      return;
    }
    if (prev === inspectorOpen) return;

    if (focusRafRef.current !== null) {
      cancelAnimationFrame(focusRafRef.current);
      focusRafRef.current = null;
    }

    const opening = inspectorOpen;
    focusRafRef.current = requestAnimationFrame(() => {
      focusRafRef.current = null;
      if (opening) {
        document.getElementById('inspector-heading')?.focus();
      } else {
        const primaryId =
          inspectorFocusReturn === 'fab' ? 'inspector-open-fab' : 'inspector-toggle-btn';
        const primary = document.getElementById(primaryId) as HTMLElement | null;
        const visible = primary && primary.offsetParent !== null;
        const target =
          visible ? primary : (document.getElementById('inspector-toggle-btn') as HTMLElement | null);
        target?.focus();
      }
    });

    prevInspectorOpen.current = inspectorOpen;
  }, [inspectorOpen, inspectorFocusReturn]);

  useEffect(() => {
    return () => {
      if (focusRafRef.current !== null) {
        cancelAnimationFrame(focusRafRef.current);
        focusRafRef.current = null;
      }
    };
  }, []);

  /**
   * Story 1.6 AC5 — zoom controls + minimap stay out of sequential tab order (decorative).
   * React Flow rerenders chrome independently of the store's `nodes` array (zoom, resize,
   * interactive toggle), so observe the flow subtree and re-apply on any DOM mutation.
   */
  useEffect(() => {
    const root = document.querySelector('.realm-flow');
    if (!root) return;
    const demote = () => {
      root.querySelectorAll<HTMLButtonElement>('.react-flow__controls button').forEach((btn) => {
        btn.setAttribute('tabindex', '-1');
      });
      const mm = root.querySelector('.react-flow__minimap');
      if (mm) mm.setAttribute('tabindex', '-1');
    };
    demote();
    const observer = new MutationObserver(demote);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  return (
    <div className="flex h-dvh max-h-dvh min-h-0 flex-col overflow-hidden bg-realm-bg text-zinc-100">
      <RealmToolbar />

      <div className="relative flex min-h-0 flex-1 flex-col md:flex-row">
        <main
          className="relative flex min-h-0 min-w-0 flex-1 flex-col"
          aria-label="Private realm command canvas"
        >
          <span className="sr-only" role="status" aria-live="polite" aria-atomic="true">
            {live}
          </span>
          <div className="relative min-h-[min(52vh,440px)] flex-1 overflow-hidden rounded-none">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              defaultEdgeOptions={defaultEdgeOptions}
              onNodeClick={onNodeClick}
              onPaneClick={() => selectNode(null)}
              fitView
              fitViewOptions={{ padding: 0.22 }}
              minZoom={0.3}
              maxZoom={1.85}
              nodeExtent={REALM_NODE_EXTENT}
              translateExtent={REALM_TRANSLATE_EXTENT}
              nodesDraggable
              nodesConnectable
              elevateNodesOnSelect
              className="realm-flow !bg-transparent"
              aria-label="Private realm network canvas. Drag nodes, pan and zoom the view, connect agents to define encrypted flows. Keyboard: use Tab to reach the graph; Space activates the selected node in some browsers."
            >
              <Background
                id="realm-grid-bg"
                variant={BackgroundVariant.Lines}
                gap={32}
                size={0.6}
                color="hsl(210 25% 38% / 0.35)"
                className="!bg-transparent"
              />
              {/* Story 1.6 AC5: decorative chrome — tab order demoted in useEffect; metrics also in StatusBar */}
              <Controls
                className="glass-panel !m-3 overflow-hidden rounded-lg !border-white/10 !shadow-glass"
                showInteractive={false}
              />
              <MiniMap
                position="bottom-right"
                nodeStrokeWidth={2}
                nodeStrokeColor="rgba(255,255,255,0.14)"
                nodeColor={(n) => scoreToMinimapColor((n.data as AgentNodeData)?.safetyScore ?? 0)}
                maskColor="rgba(15,16,24,0.88)"
                maskStrokeColor="rgba(34,211,238,0.12)"
                style={{ background: 'hsl(222 47% 4% / 0.94)' }}
                className="!m-3 mb-[4.25rem] !min-h-[104px] !min-w-[140px] !overflow-hidden !rounded-lg !border !border-white/12 !shadow-glass md:!mb-3"
                pannable
                zoomable
                aria-label="Canvas minimap — node colors match safety score tier"
              />
              <Panel
                position="top-left"
                className="glass-panel m-3 max-w-[min(100%,280px)] rounded-lg px-3 py-2 font-mono text-[10px] leading-snug text-realm-muted"
              >
                Realm bounds active · Node positions persist across soft refresh · Encrypted links are animated stubs
              </Panel>
            </ReactFlow>
          </div>
        </main>

        <aside
          id="realm-inspector"
          {...(inspectorOpen
            ? ({ 'aria-labelledby': 'inspector-heading' } as const)
            : ({ 'aria-label': 'Inspector' } as const))}
          aria-hidden={!inspectorOpen}
          className={cn(
            'flex shrink-0 flex-col border-white/10 bg-realm-bg/98 backdrop-blur-xl transition-[width,opacity,transform] duration-300 ease-out md:border-l',
            inspectorOpen
              ? 'max-h-[min(46vh,480px)] w-full translate-x-0 opacity-100 md:max-h-none md:h-full md:w-[min(420px,40vw)]'
              : 'pointer-events-none max-h-0 w-0 min-w-0 -translate-x-2 overflow-hidden border-0 opacity-0 md:max-h-none md:h-full'
          )}
        >
          {inspectorOpen ? (
            <InspectorPanel className="h-full min-h-0 max-w-none border-0" />
          ) : null}
        </aside>

        {!inspectorOpen ? (
          <Button
            type="button"
            variant="glass"
            size="icon"
            id="inspector-open-fab"
            className="fixed bottom-20 right-4 z-30 size-12 rounded-full shadow-glow-cyan md:bottom-6 md:hidden"
            onClick={() => setInspectorOpen(true, 'fab')}
            aria-controls="realm-inspector"
            aria-label="Open inspector panel"
          >
            <PanelRight className="size-5" aria-hidden />
          </Button>
        ) : null}
      </div>

      <StatusBar />
    </div>
  );
}
