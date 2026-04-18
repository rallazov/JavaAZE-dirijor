// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
//
// Canvas ↔ Core WebSocket event types (Story 3.3, schema v3).
//
// INVARIANT: payload shapes in this file MUST mirror the backend payload
// dicts in `backend/dirijor-core/supervisor.py` (search `_send_envelope`
// call sites) verbatim. If a field name diverges, fix THIS file — not the
// backend — so the realtime reducer stays a pure upsert with no translation
// layer (see `applyTopologyDelta`/`applyMetricsUpdate`/`applyHitlPending`
// in `store/canvas-store.ts`).
//
// Adding a new event type requires a backend SCHEMA_VERSION bump AND an
// additive entry in `session.hello.supported_event_types` so clients can
// feature-detect gracefully. Do NOT add new top-level envelope keys — the
// 6-key envelope is strict (Story 3.3 AC 2).

import type { AgentNodeData } from './agent';
import type { CriticalAction, RealmMetrics } from './realm';

export type DirijorRealtimeEventType =
  | 'session.hello'
  | 'topology.delta'
  | 'metrics.update'
  | 'hitl.pending'
  | 'heartbeat'
  | 'session.bye';

interface Envelope<TType extends DirijorRealtimeEventType, TPayload> {
  type: TType;
  schema_version: number;
  realm_id: string;
  /** ISO-8601 UTC with trailing Z. */
  ts: string;
  /** Monotonic per-session, starts at 0 for `session.hello`. */
  seq: number;
  payload: TPayload;
}

export interface SessionHelloPayload {
  service_version: string;
  schema_version: number;
  supported_event_types: DirijorRealtimeEventType[];
  heartbeat_interval_s: number;
  connection_id: string;
}
export type SessionHelloEvent = Envelope<'session.hello', SessionHelloPayload>;

/** Upsert/tombstone diff over the canvas graph. `{ id, _tombstone: true }`
 *  removes the entity by id; known ids are merged; unknown ids are appended.
 */
export interface TopologyDeltaPayload {
  agents?: Array<
    (Partial<AgentNodeData> & { id: string; _tombstone?: true })
  >;
  edges?: Array<{
    id: string;
    source?: string;
    target?: string;
    _tombstone?: true;
  }>;
}
export type TopologyDeltaEvent = Envelope<'topology.delta', TopologyDeltaPayload>;

/** Shallow merge into `metrics`. If `auditPreview` is present in the payload
 *  it REPLACES the existing array wholesale (see the action's JSDoc).
 */
export type MetricsUpdatePayload = Partial<RealmMetrics>;
export type MetricsUpdateEvent = Envelope<'metrics.update', MetricsUpdatePayload>;

export interface HitlPendingPayload {
  action: CriticalAction;
}
export type HitlPendingEvent = Envelope<'hitl.pending', HitlPendingPayload>;

/** Empty by contract — heartbeat is pure keep-alive. */
export type HeartbeatEvent = Envelope<'heartbeat', Record<string, never>>;

export interface SessionByePayload {
  reason: string;
}
export type SessionByeEvent = Envelope<'session.bye', SessionByePayload>;

export type DirijorRealtimeEvent =
  | SessionHelloEvent
  | TopologyDeltaEvent
  | MetricsUpdateEvent
  | HitlPendingEvent
  | HeartbeatEvent
  | SessionByeEvent;

export type DirijorRealtimeStatus =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'error';
