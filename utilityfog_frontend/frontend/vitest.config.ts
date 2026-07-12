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
      // Reporter note: vitest 4.1.10's text table omits 100%-covered files;
      // json-summary carries every file (verified against this corpus).
      reporter: ['text', 'text-summary', 'json-summary'],
      // COVERAGE CONTRACT (Package X): only explicitly unit-owned modules
      // are measured and gated. Documented exclusions —
      //   NetworkView2D/NetworkView3D/Edges/InstancedNodes/ThreeScene:
      //     WebGL/canvas surfaces, owned by the Playwright E2E suite
      //     (ui-smoke); jsdom cannot render them meaningfully.
      //   adapters.ts: legacy format adapter, not yet unit-owned.
      //   utils.ts: only the foundation slice is covered so far; joins the
      //     contract when the corpus owns the rest of it.
      //   main.tsx: bootstrap entry point.
      include: [
        'src/App.tsx',
        'src/components/ConnectionBadge.tsx',
        'src/components/EventFeed.tsx',
        'src/viz3d/nodeValidation.ts',
        'src/viz3d/useEventQueue.ts',
        'src/viz3d/useSceneStore.ts',
        'src/ws/SimBridgeClient.ts',
      ],
      // Thresholds are derived BELOW the measured stable baseline of the
      // final corpus (aggregate over the include set: statements 97.01%,
      // branches 93.10%, functions 97.50%, lines 97.38% — identical across
      // repeated runs), with a small margin for future environment
      // variance. Never raise these to aspirational values and never
      // lower them merely to make CI green.
      thresholds: {
        statements: 93,
        branches: 85,
        functions: 92,
        lines: 93,
      },
    },
  },
})
