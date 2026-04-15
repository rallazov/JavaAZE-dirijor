// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react';
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
import { useDirijorRealtime } from '@/hooks/useDirijorRealtime';
import { useCanvasStore, REALM_NODE_EXTENT, REALM_TRANSLATE_EXTENT } from '@/store/canvas-store';
import type { AgentNodeData } from '@/types/agent';
import { cn } from '@/lib/utils';
import 'reactflow/dist/style.css';

const nodeTypes = { agent: AgentNode };
const edgeTypes = { encrypted: AnimatedEdge };

export function CanvasShell() {
  const nodes = useCanvasStore((s) => s.nodes) as Node<AgentNodeData>[];
  const edges = useCanvasStore((s) => s.edges) as Edge[];
  const onNodesChange = useCanvasStore((s) => s.onNodesChange);
  const onEdgesChange = useCanvasStore((s) => s.onEdgesChange);
  const onConnect = useCanvasStore((s) => s.onConnect);
  const selectNode = useCanvasStore((s) => s.selectNode);
  const selectedId = useCanvasStore((s) => s.selectedNodeId);
  const inspectorOpen = useCanvasStore((s) => s.inspectorOpen);
  const setInspectorOpen = useCanvasStore((s) => s.setInspectorOpen);

  /** Epic 3 — pass url when Core assigns a realm session */
  useDirijorRealtime({ url: undefined, realmId: undefined });

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
              className="!bg-transparent"
              aria-label="Private realm network canvas. Drag nodes, pan and zoom the view, connect agents to define encrypted flows."
            >
              <Background
                id="realm-grid-bg"
                variant={BackgroundVariant.Lines}
                gap={32}
                size={0.6}
                color="hsl(210 25% 38% / 0.35)"
                className="!bg-transparent"
              />
              <Controls
                className="glass-panel !m-3 overflow-hidden rounded-lg !border-white/10 !shadow-glass"
                showInteractive={false}
              />
              <MiniMap
                position="bottom-right"
                nodeStrokeWidth={3}
                nodeColor={(n) => {
                  const s = (n.data as AgentNodeData)?.status;
                  if (s === 'critical') return 'hsl(350 78% 52%)';
                  if (s === 'degraded' || s === 'pending') return 'hsl(38 96% 58%)';
                  return 'hsl(186 100% 52%)';
                }}
                maskColor="rgba(0,0,0,0.78)"
                className="!glass-panel !m-3 mb-[4.25rem] !overflow-hidden !rounded-lg !border !border-white/10 md:!mb-3"
                pannable
                zoomable
                aria-label="Minimap"
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
            className="fixed bottom-20 right-4 z-30 size-12 rounded-full shadow-glow-cyan md:bottom-6 md:hidden"
            onClick={() => setInspectorOpen(true)}
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
