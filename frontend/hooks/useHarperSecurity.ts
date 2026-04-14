// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { useCallback, useState } from 'react';

export interface VerificationResult {
  agentId: string;
  verified: boolean;
  fingerprint: string;
  checkedAt: string;
}

/**
 * Harper Security layer — mTLS / policy checks / anomaly hooks (integration stub).
 */
export function useHarperSecurity() {
  const [resultsByAgentId, setResultsByAgentId] = useState<Record<string, VerificationResult>>({});

  const verifyNode = useCallback(async (agentId: string) => {
    const fingerprint = `sha256:${btoa(agentId).slice(0, 20)}…`;
    const result: VerificationResult = {
      agentId,
      verified: true,
      fingerprint,
      checkedAt: new Date().toISOString(),
    };
    setResultsByAgentId((current) => ({ ...current, [agentId]: result }));
    return result;
  }, []);

  const getVerification = useCallback(
    (agentId: string | null | undefined) => {
      if (!agentId) {
        return null;
      }

      return resultsByAgentId[agentId] ?? null;
    },
    [resultsByAgentId]
  );

  return { getVerification, verifyNode };
}
