// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { getBezierPath, BaseEdge, type EdgeProps } from 'reactflow';

/**
 * Animated “encrypted” flow — base gradient wire + moving dash packets.
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
  const pktBase = `pkt-base-${id}`;

  return (
    <>
      <defs>
        <linearGradient id={gid} x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="hsl(186 100% 52% / 0.2)" />
          <stop offset="45%" stopColor="hsl(152 76% 48% / 0.95)" />
          <stop offset="100%" stopColor="hsl(186 100% 52% / 0.25)" />
        </linearGradient>
        <linearGradient id={pktBase} x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="hsl(186 100% 52% / 0.15)" />
          <stop offset="50%" stopColor="hsl(152 76% 48% / 0.5)" />
          <stop offset="100%" stopColor="hsl(186 100% 52% / 0.15)" />
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
        stroke="url(#pktBase)"
        strokeWidth={1.15}
        strokeDasharray="6 14"
        strokeLinecap="round"
        className="animate-flow-dash pointer-events-none"
      />
      <path
        d={edgePath}
        fill="none"
        stroke="hsl(186 100% 60% / 0.92)"
        strokeWidth={2}
        strokeDasharray="3 26"
        strokeLinecap="round"
        className="animate-packet-flow pointer-events-none"
      />
      <path
        d={edgePath}
        fill="none"
        stroke="hsl(152 76% 52% / 0.88)"
        strokeWidth={1.25}
        strokeDasharray="2 34"
        strokeLinecap="round"
        className="animate-flow-dash pointer-events-none opacity-80 [animation-duration:2.6s]"
      />
    </>
  );
}
