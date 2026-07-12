import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Standalone Vitest configuration — deliberately NOT merged with
// vite.config.ts (the app config carries dev-server and optimizeDeps
// settings the unit runner doesn't need).
//
// Corpus separation contract: the unit corpus lives ONLY in tests-unit/.
// Playwright owns tests/ — its default testMatch would collect *.test.*
// files under its testDir, so the two corpora are separated at the
// directory level, sealing cross-collection in BOTH directions.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['tests-unit/**/*.test.{ts,tsx}'],
    // Explicit imports only: each test imports describe/it/expect/vi from
    // 'vitest' — no injected globals.
    globals: false,
    setupFiles: ['tests-unit/setup.ts'],
    // Deterministic isolation: spies, mocks, stubbed globals and stubbed
    // env vars are all torn down between tests.
    clearMocks: true,
    mockReset: true,
    restoreMocks: true,
    unstubGlobals: true,
    unstubEnvs: true,
    coverage: {
      provider: 'v8',
      // Package U reports coverage WITHOUT thresholds: thresholds are
      // derived from the measured baseline only after the complete unit
      // corpus exists (Package X), never chosen aspirationally.
      reporter: ['text', 'text-summary'],
      include: ['src/**/*.{ts,tsx}'],
    },
  },
})
