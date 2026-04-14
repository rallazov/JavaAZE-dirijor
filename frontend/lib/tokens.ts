// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
/** Design token map — mirror Figma variables (replace values when MCP syncs). */
export const realmTokens = {
  colors: {
    spaceBlack: 'hsl(222 47% 4%)',
    gridLine: 'hsl(210 25% 38% / 12%)',
    cyan: 'hsl(186 100% 52%)',
    emerald: 'hsl(152 76% 48%)',
    amber: 'hsl(38 96% 58%)',
    crimson: 'hsl(350 78% 52%)',
  },
  radii: {
    card: '0.875rem',
    pill: '9999px',
  },
} as const;
