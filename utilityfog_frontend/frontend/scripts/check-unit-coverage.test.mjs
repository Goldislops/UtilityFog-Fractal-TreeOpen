// Unit tests for the per-file coverage floor gate (node:test, zero deps —
// same pattern as check-bundle-budget.test.mjs).
import test from 'node:test'
import assert from 'node:assert/strict'
import { checkCoverage, FLOORS } from './check-unit-coverage.mjs'

const row = (s, b, f, l) => ({
  statements: { pct: s },
  branches: { pct: b },
  functions: { pct: f },
  lines: { pct: l },
})

// A synthetic summary satisfying every floor exactly.
function passingSummary() {
  const summary = { total: row(100, 100, 100, 100) }
  for (const [module, floors] of Object.entries(FLOORS)) {
    summary[`C:\\repo\\utilityfog_frontend\\frontend\\${module.split('/').join('\\')}`] = row(
      floors[0],
      floors[1],
      floors[2],
      floors[3],
    )
  }
  return summary
}

test('passes when every module meets its floor (windows-style absolute keys)', () => {
  const { status, failures } = checkCoverage(passingSummary())
  assert.equal(status, 'PASS')
  assert.deepEqual(failures, [])
})

test('passes with posix-style keys too', () => {
  const summary = { total: row(100, 100, 100, 100) }
  for (const [module, floors] of Object.entries(FLOORS)) {
    summary[`/repo/utilityfog_frontend/frontend/${module}`] = row(...floors)
  }
  assert.equal(checkCoverage(summary).status, 'PASS')
})

test('a single-metric regression below its floor fails with a precise message', () => {
  const summary = passingSummary()
  const key = Object.keys(summary).find(k => k.includes('nodeValidation'))
  summary[key] = row(99, 100, 100, 100) // floor is 100
  const { status, failures } = checkCoverage(summary)
  assert.equal(status, 'FAIL')
  assert.equal(failures.length, 1)
  assert.match(failures[0], /nodeValidation\.ts: statements 99% < floor 100%/)
})

test('a module MISSING from the summary fails — rows cannot silently disappear', () => {
  const summary = passingSummary()
  const key = Object.keys(summary).find(k => k.includes('edgeValidation'))
  delete summary[key]
  const { status, failures } = checkCoverage(summary)
  assert.equal(status, 'FAIL')
  assert.equal(failures.length, 1)
  assert.match(failures[0], /edgeValidation\.ts: MISSING from coverage summary/)
})

test('malformed summaries are rejected with MALFORMED status', () => {
  assert.equal(checkCoverage(null).status, 'MALFORMED')
  assert.equal(checkCoverage([]).status, 'MALFORMED')
  assert.equal(checkCoverage('junk').status, 'MALFORMED')

  const summary = passingSummary()
  const key = Object.keys(summary).find(k => k.includes('App.tsx'))
  summary[key] = { statements: { pct: 'not-a-number' } }
  const { status, failures } = checkCoverage(summary)
  assert.equal(status, 'MALFORMED')
  assert.ok(failures.some(f => f.includes('malformed')))
})

test('the floor table itself is well-formed (4 numeric floors per module)', () => {
  for (const [module, floors] of Object.entries(FLOORS)) {
    assert.equal(floors.length, 4, module)
    for (const value of floors) {
      assert.equal(typeof value, 'number', module)
      assert.ok(value >= 0 && value <= 100, module)
    }
  }
})
