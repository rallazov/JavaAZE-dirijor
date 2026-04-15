// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from 'reactflow';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import type { AgentNodeData } from '@/types/agent';
import type { RealmNode } from '@/types/canvas';
import type { CriticalAction, RealmMetrics } from '@/types/realm';

/** Logical bounds for the “vault” graph — keeps drag/pan inside a defined realm. */
export const REALM_NODE_EXTENT: [[number, number], [number, number]] = [
  [-120, -80],
  [2200, 1680],
];

export const REALM_TRANSLATE_EXTENT: [[number, number], [number, number]] = [
  [-960, -640],
  [2880, 2240],
];

const CANVAS_STORAGE_KEY = 'dirijor-private-realm-canvas:v1';

const initialNodes: RealmNode[] = [
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
  nodes: RealmNode[];
  edges: Edge[];
  selectedNodeId: string | null;
  metrics: RealmMetrics;
  pendingActions: CriticalAction[];
  realmDescription: string;
  /** Progressive disclosure: inspector column visibility (not persisted). */
  inspectorOpen: boolean;
  /** Active realm for realtime + toolbar (stub multi-realm; not persisted). */
  activeRealmId: string;
  setRealmDescription: (v: string) => void;
  setActiveRealmId: (id: string) => void;
  setInspectorOpen: (open: boolean) => void;
  toggleInspector: () => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  selectNode: (id: string | null) => void;
  removePending: (id: string) => void;
  /** Resets graph, metrics, HITL queue, and realm description to the bundled demo (also used on bad rehydrate). */
  resetGraphToDemo: () => void;
}

type PersistedCanvasSlice = Pick<CanvasStore, 'nodes' | 'edges' | 'realmDescription'>;

function defaultPersistedSlice(): PersistedCanvasSlice {
  return {
    nodes: initialNodes,
    edges: initialEdges,
    realmDescription: '',
  };
}

/** Guard against corrupt JSON or hand-edited localStorage that still parses. */
function coercePersistedSlice(value: unknown): PersistedCanvasSlice | null {
  if (!value || typeof value !== 'object') return null;
  const v = value as Record<string, unknown>;
  if (!Array.isArray(v.nodes) || !Array.isArray(v.edges)) return null;
  for (const n of v.nodes) {
    if (!n || typeof n !== 'object') return null;
    const nn = n as Record<string, unknown>;
    if (typeof nn.id !== 'string') return null;
    if (!nn.position || typeof nn.position !== 'object') return null;
    const pos = nn.position as Record<string, unknown>;
    if (typeof pos.x !== 'number' || typeof pos.y !== 'number') return null;
  }
  for (const e of v.edges) {
    if (!e || typeof e !== 'object') return null;
    const ee = e as Record<string, unknown>;
    if (typeof ee.id !== 'string' || typeof ee.source !== 'string' || typeof ee.target !== 'string') {
      return null;
    }
  }
  if (v.realmDescription !== undefined && typeof v.realmDescription !== 'string') return null;
  return {
    nodes: v.nodes as RealmNode[],
    edges: v.edges as Edge[],
    realmDescription: typeof v.realmDescription === 'string' ? v.realmDescription : '',
  };
}

export const useCanvasStore = create<CanvasStore>()(
  persist(
    (set, get) => ({
      nodes: initialNodes,
      edges: initialEdges,
      selectedNodeId: null,
      metrics: initialMetrics,
      pendingActions: initialPending,
      realmDescription: '',
      inspectorOpen: true,
      activeRealmId: 'local',
      setRealmDescription: (realmDescription) => set({ realmDescription }),
      setActiveRealmId: (activeRealmId) => set({ activeRealmId }),
      setInspectorOpen: (inspectorOpen) => set({ inspectorOpen }),
      toggleInspector: () => set((s) => ({ inspectorOpen: !s.inspectorOpen })),
      onNodesChange: (changes) => set({ nodes: applyNodeChanges(changes, get().nodes) }),
      onEdgesChange: (changes) => set({ edges: applyEdgeChanges(changes, get().edges) }),
      onConnect: (connection) => set({ edges: addEdge(connection, get().edges) }),
      selectNode: (id) => set({ selectedNodeId: id }),
      removePending: (id) =>
        set((s) => ({ pendingActions: s.pendingActions.filter((p) => p.id !== id) })),
      resetGraphToDemo: () =>
        set({
          ...defaultPersistedSlice(),
          selectedNodeId: null,
          metrics: initialMetrics,
          pendingActions: initialPending,
        }),
    }),
    {
      name: CANVAS_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      version: 1,
      partialize: (state) => ({
        nodes: state.nodes,
        edges: state.edges,
        realmDescription: state.realmDescription,
      }),
      migrate: (persisted, _fromVersion) =>
        coercePersistedSlice(persisted) ?? defaultPersistedSlice(),
      merge: (persistedState, currentState) => {
        const safe = coercePersistedSlice(persistedState);
        if (!safe) return currentState;
        return { ...currentState, ...safe };
      },
      onRehydrateStorage: () => (_state, error) => {
        if (error) {
          useCanvasStore.setState({
            ...defaultPersistedSlice(),
            selectedNodeId: null,
            metrics: initialMetrics,
            pendingActions: initialPending,
          });
        }
      },
    }
  )
);
