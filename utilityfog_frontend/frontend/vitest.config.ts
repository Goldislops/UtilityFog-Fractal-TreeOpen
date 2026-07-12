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
      // COVERAGE CONTRACT (Packages X/Y/Z): only explicitly unit-owned
      // modules are measured and gated. Documented exclusions —
      //   NetworkView3D/Edges/InstancedNodes/ThreeScene: WebGL surfaces,
      //     owned by the Playwright E2E suite (ui-smoke); jsdom cannot
      //     render them meaningfully.
      //   utils.ts: only the foundation slice is covered so far; joins the
      //     contract when the corpus owns the rest of it.
      //   main.tsx: bootstrap entry point.
      // NetworkView2D joined in Package Z with its subscription/ingress
      // paths unit-owned; its canvas DRAW effect body is unreachable under
      // jsdom (getContext → null, the component's own guarded early
      // return), which is why the aggregate baseline steps down from
      // Package Y's 97/94/97/97 — a scope expansion, not a coverage
      // regression (every previously-owned module kept its numbers).
      include: [
        'src/App.tsx',
        'src/components/ConnectionBadge.tsx',
        'src/components/EventFeed.tsx',
        'src/components/NetworkView2D.tsx',
        'src/viz3d/adapters.ts',
        'src/viz3d/edgeValidation.ts',
        'src/viz3d/nodeValidation.ts',
        'src/viz3d/useEventQueue.ts',
        'src/viz3d/useSceneStore.ts',
        'src/ws/SimBridgeClient.ts',
      ],
      // Thresholds are derived BELOW the measured stable baseline of the
      // final corpus. Package Z baseline over the expanded include set
      // (three repeated runs): statements 90.00, functions 94.33, lines
      // 90.63 — identical each run; branches 91.44–91.74 (one
      // nondeterministic branch in the adapter's random-fallback path), so
      // derivation uses the observed FLOOR. Margin ≈4 points for future
      // environment variance. This re-derivation accompanies a SCOPE
      // EXPANSION (NetworkView2D + adapters joined the contract; every
      // previously-owned module kept its Package-Y numbers) — it is not a
      // coverage reduction. Never raise these to aspirational values and
      // never lower them merely to make CI green.
      thresholds: {
        statements: 86,
        branches: 87,
        functions: 90,
        lines: 86,
      },
    },
  },
})
