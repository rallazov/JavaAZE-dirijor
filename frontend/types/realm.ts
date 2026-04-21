// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

export interface RealmMetrics {
  /** Median edge latency (ms) */
  latencyMs: number;
  /** 0–100 aggregate posture */
  securityPosture: number;
  /** Recent immutable audit entries (preview only) */
  auditPreview: { id: string; at: string; summary: string }[];
  /** Story 6.3 — agents currently quarantined in this realm (Core HUD). */
  quarantinedAgentCount: number;
}

export interface CriticalAction {
  id: string;
  title: string;
  detail: string;
  /** ISO-8601 timestamp from the live approval queue when available. */
  requestedAt?: string | null;
  safetyScore: number;
}
