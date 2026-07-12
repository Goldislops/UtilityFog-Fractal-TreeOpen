#!/usr/bin/env node
// Lint-rule liveness gate (Package AI): proves each load-bearing rule in
// the flat config still FIRES by linting deliberate-violation fixtures
// (lint-fixtures/, excluded from the normal lint run and from tsconfig),
// and that the viz3d react-property exception still HOLDS on a real scene
// file. Guards against silently weakened configuration.
//   node scripts/check-lint-rules.mjs        -> exit 0 when every
//   expectation holds; exit 1 with a report otherwise.
import { ESLint } from 'eslint'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// cwd-INDEPENDENT (audit amendment): the frontend root is resolved from
// THIS FILE's location, never from the caller's working directory — the
// gate behaves identically from the frontend dir, the repo root, or any
// unrelated cwd (all three receipted).
const FRONTEND_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')

const EXPECTATIONS = [
  {
    file: 'lint-fixtures/explicit-any.ts',
    rule: '@typescript-eslint/no-explicit-any',
    expect: 'fires',
  },
  {
    file: 'lint-fixtures/hooks-violation.tsx',
    rule: 'react-hooks/rules-of-hooks',
    expect: 'fires',
  },
  {
    file: 'lint-fixtures/unknown-property.tsx',
    rule: 'react/no-unknown-property',
    expect: 'fires',
  },
  {
    file: 'lint-fixtures/refresh-violation.tsx',
    rule: 'react-refresh/only-export-components',
    expect: 'fires',
  },
  {
    // Ownership contract: unused vars are tsc's job — the rule must stay
    // silent here even though the fixture contains one.
    file: 'lint-fixtures/unused-var.ts',
    rule: '@typescript-eslint/no-unused-vars',
    expect: 'silent',
  },
  {
    // The narrowly justified exception: reconciler props on a REAL viz3d
    // scene file must not trigger react/no-unknown-property.
    file: 'src/viz3d/NetworkView3D.tsx',
    rule: 'react/no-unknown-property',
    expect: 'silent',
  },
]

const eslint = new ESLint({ ignore: false, cwd: FRONTEND_ROOT })
const failures = []
for (const { file, rule, expect } of EXPECTATIONS) {
  const [result] = await eslint.lintFiles([resolve(FRONTEND_ROOT, file)])
  const hits = result.messages.filter((m) => m.ruleId === rule)
  const fired = hits.length > 0
  if (expect === 'fires' && !fired) {
    failures.push(`${file}: expected ${rule} to fire — it did not (rule weakened?)`)
  }
  if (expect === 'silent' && fired) {
    failures.push(`${file}: expected ${rule} to stay silent — it fired ${hits.length}x`)
  }
}

for (const failure of failures) console.error(`  ${failure}`)
console.log(
  `LINT_RULES v1 expectations=${EXPECTATIONS.length} failures=${failures.length} status=${failures.length === 0 ? 'PASS' : 'FAIL'}`,
)
process.exit(failures.length === 0 ? 0 : 1)
