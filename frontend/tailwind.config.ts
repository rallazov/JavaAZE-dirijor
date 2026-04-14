import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: 'class',
  content: ['./app/**/*.{js,ts,jsx,tsx}', './components/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        realm: {
          bg: 'hsl(var(--realm-bg) / <alpha-value>)',
          grid: 'hsl(var(--realm-grid) / <alpha-value>)',
          glass: 'hsl(var(--realm-glass) / <alpha-value>)',
          border: 'hsl(var(--realm-border) / <alpha-value>)',
          cyan: 'hsl(var(--realm-cyan) / <alpha-value>)',
          emerald: 'hsl(var(--realm-emerald) / <alpha-value>)',
          amber: 'hsl(var(--realm-amber) / <alpha-value>)',
          crimson: 'hsl(var(--realm-crimson) / <alpha-value>)',
          muted: 'hsl(var(--realm-muted) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        glass: '0 0 0 1px hsl(var(--realm-border) / 0.35), 0 24px 48px -12px rgb(0 0 0 / 0.65)',
        'glow-cyan': '0 0 32px hsl(var(--realm-cyan) / 0.35)',
        'glow-emerald': '0 0 28px hsl(var(--realm-emerald) / 0.3)',
        'glow-amber': '0 0 22px hsl(var(--realm-amber) / 0.35)',
        'glow-crimson': '0 0 26px hsl(var(--realm-crimson) / 0.45)',
      },
      keyframes: {
        'flow-dash': {
          '0%': { strokeDashoffset: '24' },
          '100%': { strokeDashoffset: '0' },
        },
        'ring-pulse': {
          '0%, 100%': { opacity: '0.55' },
          '50%': { opacity: '1' },
        },
      },
      animation: {
        'flow-dash': 'flow-dash 1.1s linear infinite',
        'ring-pulse': 'ring-pulse 2.8s ease-in-out infinite',
      },
      backgroundImage: {
        'realm-grid':
          'linear-gradient(hsl(var(--realm-grid) / 0.08) 1px, transparent 1px), linear-gradient(90deg, hsl(var(--realm-grid) / 0.08) 1px, transparent 1px)',
      },
    },
  },
  plugins: [],
};

export default config;
