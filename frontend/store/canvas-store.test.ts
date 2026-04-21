// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
// @vitest-environment node

import { describe, expect, it } from 'vitest';
import type { RealmMetrics } from '@/types/realm';
import { mergeRealmMetrics } from './canvas-store';

describe('mergeRealmMetrics (Story 6.3)', () => {
  const base: RealmMetrics = {
    latencyMs: 40,
    securityPosture: 90,
    quarantinedAgentCount: 0,
    auditPreview: [{ id: 'a1', at: 't1', summary: 'old' }],
  };

  it('shallow-merges scalar keys including quarantinedAgentCount', () => {
    const next = mergeRealmMetrics(base, { latencyMs: 55, quarantinedAgentCount: 2 });
    expect(next.latencyMs).toBe(55);
    expect(next.quarantinedAgentCount).toBe(2);
    expect(next.securityPosture).toBe(90);
    expect(next.auditPreview).toEqual(base.auditPreview);
  });

  it('replaces auditPreview wholesale when the key is present', () => {
    const next = mergeRealmMetrics(base, {
      auditPreview: [{ id: 'b', at: 't2', summary: 'new only' }],
    });
    expect(next.auditPreview).toEqual([{ id: 'b', at: 't2', summary: 'new only' }]);
  });

  it('clears auditPreview when payload passes an empty array', () => {
    const next = mergeRealmMetrics(base, { auditPreview: [] });
    expect(next.auditPreview).toEqual([]);
  });
});
