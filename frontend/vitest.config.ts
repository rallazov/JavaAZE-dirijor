// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
//
// Vitest config for the Dirijor frontend.
//
// Story 3.3 AC 8 / AC 10: tests run in `node` env (pure-module testing —
// no DOM needed). Hook + component tests are NOT in scope for 3.3; that
// requires jsdom + a WS polyfill (mock-socket) and is deferred to a future
// "testing harness" story.
//
// Path aliases mirror `tsconfig.json`'s `"@/*"` → `"./*"` so test files can
// import from e.g. `@/types/realtime` without relative-path gymnastics.

import { defineConfig } from 'vitest/config';
import path from 'node:path';

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
  test: {
    environment: 'node',
    include: ['**/*.test.ts'],
    exclude: ['node_modules/**', '.next/**'],
  },
});
