// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

export type AgentStatus = 'healthy' | 'degraded' | 'critical' | 'pending';

export type AgentRole = 'human' | 'grok' | 'security' | 'code' | 'custom';

export interface AgentNodeData {
  label: string;
  role: AgentRole;
  /** 0–1 verified safety score from Harper / consensus */
  safetyScore: number;
  status: AgentStatus;
  /** Round-trip latency hint for UI (ms); WebSocket hook will hydrate */
  latencyMs?: number;
  /** Last verification fingerprint (placeholder until backend) */
  signaturePreview?: string;
}
