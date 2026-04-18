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
import type {
  DirijorRealtimeStatus,
  HitlPendingPayload,
  MetricsUpdatePayload,
  TopologyDeltaPayload,
} from '@/types/realtime';

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
  /** Last control that opened the inspector — used to restore focus on close (a11y). */
  inspectorFocusReturn: 'toolbar' | 'fab';
  /** Active realm for realtime + toolbar (stub multi-realm; not persisted). */
  activeRealmId: string;
  /** Story 3.3 — current transport status mirrored from `useDirijorRealtime`
   *  so any component can render a label without re-running the hook.
   *  Not persisted (rebuilt on mount by the hook). */
  realtimeStatus: DirijorRealtimeStatus;
  setRealmDescription: (v: string) => void;
  setActiveRealmId: (id: string) => void;
  setInspectorOpen: (open: boolean, focusFrom?: 'toolbar' | 'fab') => void;
  toggleInspector: (focusFrom?: 'toolbar' | 'fab') => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  selectNode: (id: string | null) => void;
  removePending: (id: string) => void;
  /** Resets graph, metrics, HITL queue, and realm description to the bundled demo (also used on bad rehydrate). */
  resetGraphToDemo: () => void;
  /** Story 3.3 AC 4 — upsert/tombstone agents + edges from a topology.delta
   *  frame. Unknown ids are appended; `_tombstone: true` removes by id. */
  applyTopologyDelta: (payload: TopologyDeltaPayload) => void;
  /** Story 3.3 AC 4 — shallow merge into `metrics`. IMPORTANT: if
   *  `auditPreview` is present on the payload it REPLACES the existing
   *  array wholesale. Shallow-merging an array is ambiguous (per-index vs
   *  concat), so we deliberately do not. */
  applyMetricsUpdate: (payload: MetricsUpdatePayload) => void;
  /** Story 3.3 AC 4 — dedup by `action.id`. Existing id → in-place update;
   *  new id → append to the pending queue. */
  applyHitlPending: (payload: HitlPendingPayload) => void;
  /** Story 3.3 — called by `useDirijorRealtime` on every transport status
   *  transition. Consumed by `StatusBar`. */
  setRealtimeStatus: (status: DirijorRealtimeStatus) => void;
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
      inspectorFocusReturn: 'toolbar',
      activeRealmId: 'local',
      realtimeStatus: 'idle',
      setRealmDescription: (realmDescription) => set({ realmDescription }),
      setActiveRealmId: (activeRealmId) => set({ activeRealmId }),
      setRealtimeStatus: (realtimeStatus) => set({ realtimeStatus }),
      setInspectorOpen: (open, focusFrom = 'toolbar') =>
        set((s) =>
          open
            ? { inspectorOpen: true, inspectorFocusReturn: focusFrom }
            : { inspectorOpen: false }
        ),
      toggleInspector: (focusFrom = 'toolbar') =>
        set((s) =>
          s.inspectorOpen
            ? { inspectorOpen: false }
            : { inspectorOpen: true, inspectorFocusReturn: focusFrom }
        ),
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
          inspectorFocusReturn: 'toolbar',
        }),
      applyTopologyDelta: (payload) =>
        set((state) => {
          let nextNodes = state.nodes;
          let nextEdges = state.edges;

          if (payload.agents && payload.agents.length > 0) {
            const nodeIndex = new Map(state.nodes.map((n, i) => [n.id, i] as const));
            nextNodes = state.nodes.slice();
            for (const a of payload.agents) {
              if (!a.id) continue;
              if (a._tombstone) {
                const idx = nodeIndex.get(a.id);
                if (idx !== undefined) {
                  nextNodes.splice(idx, 1);
                  // Rebuild the index because positions shifted.
                  nodeIndex.clear();
                  nextNodes.forEach((n, i) => nodeIndex.set(n.id, i));
                }
                continue;
              }
              const idx = nodeIndex.get(a.id);
              const { id: _skipId, _tombstone: _skipT, ...dataPatch } = a;
              void _skipId;
              void _skipT;
              if (idx !== undefined) {
                const existing = nextNodes[idx];
                nextNodes[idx] = {
                  ...existing,
                  data: { ...existing.data, ...(dataPatch as Partial<AgentNodeData>) },
                };
              } else {
                // New node arriving from the backend. Position is not
                // authoritative from the backend; seed at origin so React
                // Flow still lays it out (future stories may add layout
                // hints via a dedicated event type).
                nextNodes.push({
                  id: a.id,
                  type: 'agent',
                  position: { x: 0, y: 0 },
                  data: {
                    label: a.id,
                    role: 'custom',
                    safetyScore: 0,
                    status: 'pending',
                    ...(dataPatch as Partial<AgentNodeData>),
                  } as AgentNodeData,
                });
                nodeIndex.set(a.id, nextNodes.length - 1);
              }
            }
          }

          if (payload.edges && payload.edges.length > 0) {
            const edgeIndex = new Map(state.edges.map((e, i) => [e.id, i] as const));
            nextEdges = state.edges.slice();
            for (const e of payload.edges) {
              if (!e.id) continue;
              if (e._tombstone) {
                const idx = edgeIndex.get(e.id);
                if (idx !== undefined) {
                  nextEdges.splice(idx, 1);
                  edgeIndex.clear();
                  nextEdges.forEach((x, i) => edgeIndex.set(x.id, i));
                }
                continue;
              }
              const idx = edgeIndex.get(e.id);
              if (idx !== undefined) {
                nextEdges[idx] = {
                  ...nextEdges[idx],
                  ...(e.source !== undefined ? { source: e.source } : {}),
                  ...(e.target !== undefined ? { target: e.target } : {}),
                };
              } else if (e.source && e.target) {
                nextEdges.push({
                  id: e.id,
                  source: e.source,
                  target: e.target,
                  type: 'encrypted',
                });
                edgeIndex.set(e.id, nextEdges.length - 1);
              }
            }
          }

          if (nextNodes === state.nodes && nextEdges === state.edges) return state;
          return { nodes: nextNodes, edges: nextEdges };
        }),
      applyMetricsUpdate: (payload) =>
        set((state) => ({
          metrics: { ...state.metrics, ...payload },
        })),
      applyHitlPending: (payload) =>
        set((state) => {
          const next = state.pendingActions.slice();
          const idx = next.findIndex((p) => p.id === payload.action.id);
          if (idx >= 0) {
            next[idx] = { ...next[idx], ...payload.action };
          } else {
            next.push(payload.action);
          }
          return { pendingActions: next };
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
