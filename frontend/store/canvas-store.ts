// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from 'reactflow';
import { create } from 'zustand';
import type { AgentNodeData } from '@/types/agent';
import type { CriticalAction, RealmMetrics } from '@/types/realm';

const initialNodes: Node<AgentNodeData>[] = [
  {
    id: '1',
    type: 'agent',
    position: { x: 80, y: 120 },
    data: {
      label: 'You',
      role: 'human',
      safetyScore: 1,
      status: 'healthy',
      latencyMs: 12,
      signaturePreview: 'ed25519:primary…',
    },
  },
  {
    id: '2',
    type: 'agent',
    position: { x: 420, y: 60 },
    data: {
      label: 'Grok Agent',
      role: 'grok',
      safetyScore: 0.97,
      status: 'healthy',
      latencyMs: 28,
      signaturePreview: 'mTLS: realm-grok-01',
    },
  },
  {
    id: '3',
    type: 'agent',
    position: { x: 400, y: 280 },
    data: {
      label: 'Harper Security',
      role: 'security',
      safetyScore: 0.99,
      status: 'healthy',
      latencyMs: 19,
      signaturePreview: 'policy:v2.4 · HMAC',
    },
  },
  {
    id: '4',
    type: 'agent',
    position: { x: 760, y: 160 },
    data: {
      label: 'Lucas Code',
      role: 'code',
      safetyScore: 0.94,
      status: 'degraded',
      latencyMs: 54,
      signaturePreview: 'build-signing: pending',
    },
  },
];

const initialEdges: Edge[] = [
  { id: 'e1-2', source: '1', target: '2', type: 'encrypted' },
  { id: 'e1-3', source: '1', target: '3', type: 'encrypted' },
  { id: 'e2-4', source: '2', target: '4', type: 'encrypted' },
  { id: 'e3-4', source: '3', target: '4', type: 'encrypted' },
];

const initialMetrics: RealmMetrics = {
  latencyMs: 34,
  securityPosture: 91,
  auditPreview: [
    { id: 'a1', at: '2m ago', summary: 'Realm boundary verified · mTLS handshake OK' },
    { id: 'a2', at: '6m ago', summary: 'Consensus quorum 0.97 on routing policy' },
  ],
};

const initialPending: CriticalAction[] = [
  {
    id: 'pa-1',
    title: 'Outbound tool: apply Terraform diff',
    detail: 'Lucas Code requests write to VPC route tables (realm prod).',
    requestedAt: null,
    safetyScore: 0.72,
  },
];

interface CanvasStore {
  nodes: Node<AgentNodeData>[];
  edges: Edge[];
  selectedNodeId: string | null;
  metrics: RealmMetrics;
  pendingActions: CriticalAction[];
  realmDescription: string;
  setRealmDescription: (v: string) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  selectNode: (id: string | null) => void;
  removePending: (id: string) => void;
}

export const useCanvasStore = create<CanvasStore>((set, get) => ({
  nodes: initialNodes,
  edges: initialEdges,
  selectedNodeId: null,
  metrics: initialMetrics,
  pendingActions: initialPending,
  realmDescription: '',
  setRealmDescription: (realmDescription) => set({ realmDescription }),
  onNodesChange: (changes) => set({ nodes: applyNodeChanges(changes, get().nodes) }),
  onEdgesChange: (changes) => set({ edges: applyEdgeChanges(changes, get().edges) }),
  onConnect: (connection) => set({ edges: addEdge(connection, get().edges) }),
  selectNode: (id) => set({ selectedNodeId: id }),
  removePending: (id) =>
    set((s) => ({ pendingActions: s.pendingActions.filter((p) => p.id !== id) })),
}));
