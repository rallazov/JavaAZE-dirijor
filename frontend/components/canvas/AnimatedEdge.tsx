// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { getBezierPath, BaseEdge, type EdgeProps } from 'reactflow';

/**
 * Animated “encrypted” flow — dash overlay suggests ciphertext in transit.
 */
export function AnimatedEdge(props: EdgeProps) {
  const {
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    style,
    markerEnd,
  } = props;

  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const gid = `enc-${id}`;

  return (
    <>
      <defs>
        <linearGradient id={gid} x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="hsl(186 100% 52% / 0.2)" />
          <stop offset="45%" stopColor="hsl(152 76% 48% / 0.95)" />
          <stop offset="100%" stopColor="hsl(186 100% 52% / 0.25)" />
        </linearGradient>
      </defs>
      <BaseEdge
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          stroke: `url(#${gid})`,
          strokeWidth: 2.75,
        }}
      />
      <path
        d={edgePath}
        fill="none"
        stroke="hsl(186 100% 52% / 0.85)"
        strokeWidth={1}
        strokeDasharray="6 12"
        className="animate-flow-dash pointer-events-none"
      />
    </>
  );
}
