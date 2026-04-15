// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

/** Numeric tiers for rings / minimap (badge remains status enum). */
export type SafetyScoreTier = 'high' | 'mid' | 'low';

const TIER_THRESH_HIGH = 0.95;
const TIER_THRESH_MID = 0.8;

export function getSafetyScoreTier(score: number): SafetyScoreTier {
  if (score >= TIER_THRESH_HIGH) return 'high';
  if (score >= TIER_THRESH_MID) return 'mid';
  return 'low';
}

/** Tailwind text/utility colors for score tier accents */
export const safetyTierTextClass: Record<SafetyScoreTier, string> = {
  high: 'text-realm-cyan',
  mid: 'text-realm-amber',
  low: 'text-realm-crimson',
};

/** Outer pulse ring animation classes (paired with stroke-* on SVG) */
export const safetyTierOuterPulseClass: Record<SafetyScoreTier, string> = {
  high: 'animate-safety-pulse-fast stroke-realm-cyan',
  mid: 'animate-safety-pulse-medium stroke-realm-amber',
  low: 'animate-safety-pulse-slow stroke-realm-crimson',
};

/** Progress arc stroke (Tailwind classes for SVG) */
export const safetyTierProgressStrokeClass: Record<SafetyScoreTier, string> = {
  high: 'stroke-realm-cyan',
  mid: 'stroke-realm-amber',
  low: 'stroke-realm-crimson',
};

/** Minimap node fills — match agent ring semantics */
export function scoreToMinimapColor(score: number): string {
  const t = getSafetyScoreTier(score);
  if (t === 'high') return 'hsl(186 100% 52%)';
  if (t === 'mid') return 'hsl(38 96% 58%)';
  return 'hsl(350 78% 52%)';
}
