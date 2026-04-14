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
import { AgentNode } from '@/components/canvas/AgentNode';
import { AnimatedEdge } from '@/components/canvas/AnimatedEdge';
import { InspectorPanel } from '@/components/inspector/InspectorPanel';
import { RealmToolbar } from '@/components/canvas/RealmToolbar';
import { StatusBar } from '@/components/canvas/StatusBar';
import { useCanvasStore } from '@/store/canvas-store';
import type { AgentNodeData } from '@/types/agent';
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
    <div className="flex h-dvh flex-col text-zinc-100">
      <RealmToolbar />
      <div
        className="flex min-h-0 flex-1 flex-col bg-realm-bg bg-realm-grid bg-[length:32px_32px] md:flex-row"
        role="presentation"
      >
        <div className="relative min-h-[min(55vh,480px)] min-w-0 flex-1">
          <span className="sr-only" role="status" aria-live="polite">
            {live}
          </span>
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
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.35}
            maxZoom={1.65}
            nodesDraggable
            nodesConnectable
            elevateNodesOnSelect
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
              nodeStrokeWidth={3}
              nodeColor={(n) => {
                const s = (n.data as AgentNodeData)?.status;
                if (s === 'critical') return 'hsl(350 78% 52%)';
                if (s === 'degraded' || s === 'pending') return 'hsl(38 96% 58%)';
                return 'hsl(186 100% 52%)';
              }}
              maskColor="rgba(0,0,0,0.78)"
              className="!glass-panel !m-3 !overflow-hidden !rounded-lg !border !border-white/10"
              pannable
              zoomable
              aria-label="Minimap"
            />
            <Panel
              position="top-left"
              className="glass-panel m-3 max-w-[min(100%,280px)] rounded-lg px-3 py-2 font-mono text-[10px] text-realm-muted"
            >
              End-to-end encrypted links · Drag nodes · Approve destructive steps in the inspector
            </Panel>
          </ReactFlow>
        </div>
        <InspectorPanel className="max-h-[45vh] md:max-h-none md:w-[min(420px,40vw)]" />
      </div>
      <StatusBar />
    </div>
  );
}
