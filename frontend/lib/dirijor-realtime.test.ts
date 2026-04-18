// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
// @vitest-environment node
//
// Unit tests for the pure WS-client module. Runs in Vitest's node env
// (no jsdom) — `createRealtimeClient` needs a real WebSocket global to
// exercise, so we mock it only where used. The pure helpers
// (`buildWsUrl` / `computeBackoffMs` / `shouldRetryOnClose` /
// `resolveDirijorWsUrl`) have no DOM dependency and are the core of
// Story 3.3 AC 8 frontend coverage.

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  buildWsUrl,
  computeBackoffMs,
  HEARTBEAT_GRACE_MULTIPLIER,
  MAX_RECONNECT_ATTEMPTS,
  resolveDirijorWsUrl,
  shouldRetryOnClose,
} from './dirijor-realtime';

describe('resolveDirijorWsUrl', () => {
  it('returns undefined for undefined input', () => {
    expect(resolveDirijorWsUrl(undefined)).toBeUndefined();
  });

  it('returns undefined for empty string (AC 5 — canvas stays runnable with no backend)', () => {
    expect(resolveDirijorWsUrl('')).toBeUndefined();
  });

  it('returns undefined for whitespace-only input', () => {
    expect(resolveDirijorWsUrl('   ')).toBeUndefined();
  });

  it('echoes a well-formed URL', () => {
    expect(resolveDirijorWsUrl('ws://127.0.0.1:8000/ws/realm')).toBe(
      'ws://127.0.0.1:8000/ws/realm'
    );
  });
});

describe('buildWsUrl', () => {
  it('returns undefined when base is missing', () => {
    expect(buildWsUrl(undefined, 'demo')).toBeUndefined();
  });

  it('appends the realmId to the base', () => {
    expect(buildWsUrl('ws://host/ws/realm', 'demo')).toBe(
      'ws://host/ws/realm/demo'
    );
  });

  it('strips trailing slashes on the base', () => {
    expect(buildWsUrl('ws://host/ws/realm/', 'demo')).toBe(
      'ws://host/ws/realm/demo'
    );
    expect(buildWsUrl('ws://host/ws/realm///', 'demo')).toBe(
      'ws://host/ws/realm/demo'
    );
  });

  it('defaults to "default" when realmId is undefined', () => {
    expect(buildWsUrl('ws://host/ws/realm', undefined)).toBe(
      'ws://host/ws/realm/default'
    );
  });

  it('defaults to "default" when realmId is whitespace', () => {
    expect(buildWsUrl('ws://host/ws/realm', '   ')).toBe(
      'ws://host/ws/realm/default'
    );
  });

  it('URL-encodes special characters in the realmId', () => {
    expect(buildWsUrl('ws://host/ws/realm', 'a b/c')).toBe(
      'ws://host/ws/realm/a%20b%2Fc'
    );
  });
});

describe('computeBackoffMs', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('stays within [500, 1000) for attempt 0', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0);
    expect(computeBackoffMs(0)).toBe(500);
    vi.spyOn(Math, 'random').mockReturnValue(0.999);
    expect(computeBackoffMs(0)).toBeLessThan(1000);
    expect(computeBackoffMs(0)).toBeGreaterThanOrEqual(500);
  });

  it('caps the deterministic part at 30_000 ms', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0);
    expect(computeBackoffMs(10)).toBe(30_000);
    expect(computeBackoffMs(100)).toBe(30_000);
  });

  it('upper-bounds the total (incl. jitter) at < 30_500 ms', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.999999);
    expect(computeBackoffMs(20)).toBeLessThan(30_500);
    expect(computeBackoffMs(20)).toBeGreaterThanOrEqual(30_000);
  });

  it('is monotonic non-decreasing on the deterministic part (random=0)', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0);
    const series = [0, 1, 2, 3, 4, 5, 6, 7, 8].map(computeBackoffMs);
    for (let i = 1; i < series.length; i += 1) {
      expect(series[i]).toBeGreaterThanOrEqual(series[i - 1]);
    }
  });

  it('clamps negative / fractional attempts defensively', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0);
    expect(computeBackoffMs(-5)).toBe(500);
    expect(computeBackoffMs(1.9)).toBe(500 * 2 ** 1);
  });
});

describe('shouldRetryOnClose', () => {
  it('returns false for client-fault codes 4401 / 4403', () => {
    expect(shouldRetryOnClose(4401)).toBe(false);
    expect(shouldRetryOnClose(4403)).toBe(false);
  });

  it('returns true for server / transport codes that we should retry on', () => {
    expect(shouldRetryOnClose(1000)).toBe(true); // clean close
    expect(shouldRetryOnClose(1006)).toBe(true); // abnormal transport close
    expect(shouldRetryOnClose(1011)).toBe(true); // server-initiated cleanup
    expect(shouldRetryOnClose(4000)).toBe(true); // our own heartbeat_grace close
  });
});

describe('module constants', () => {
  it('pins retry ceiling at 8 attempts (AC 6)', () => {
    expect(MAX_RECONNECT_ATTEMPTS).toBe(8);
  });

  it('pins the heartbeat grace multiplier at 2× (AC 3 / AC 6)', () => {
    expect(HEARTBEAT_GRACE_MULTIPLIER).toBe(2);
  });
});
