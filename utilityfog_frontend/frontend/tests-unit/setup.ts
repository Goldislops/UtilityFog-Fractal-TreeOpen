// Shared unit-test setup, loaded once per test file (vitest.config.ts
// setupFiles).
//
// jest-dom's vitest entry registers the DOM matchers (toBeInTheDocument,
// toHaveAttribute, ...) on Vitest's expect via module augmentation.
import '@testing-library/jest-dom/vitest'

import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// Deterministic DOM teardown. Testing Library's automatic cleanup relies on
// a GLOBAL afterEach hook, which this project deliberately does not inject
// (globals: false) — so cleanup is registered explicitly here. Every test
// starts with an empty document regardless of what the previous test
// rendered; tests-unit/foundation-cleanup asserts this contract directly.
afterEach(() => {
  cleanup()
})
