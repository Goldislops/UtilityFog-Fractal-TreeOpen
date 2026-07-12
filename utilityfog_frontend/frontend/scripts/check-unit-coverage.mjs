#!/usr/bin/env node
// Per-file unit-coverage floor gate (Package AC).
//
// Makes "scope expansion did not weaken existing coverage" MECHANICALLY
// true: every unit-owned module carries an explicit checked-in floor, a
// module missing from the coverage summary FAILS (it cannot silently
// disappear from the report), and a malformed summary fails with its own
// exit code.
//
// Why not vitest's native per-file thresholds: the installed vitest
// supports `coverage.thresholds.perFile` (verified in its local dist),
// but that applies the GLOBAL thresholds uniformly per file; glob-keyed
// thresholds exist but neither missing-row failure nor malformed-summary
// diagnostics are contractually guaranteed there. This checker owns all
// three semantics and is unit-tested for them.
//
// Floor derivation (documented evidence): per-file numbers measured at
// the AC head, byte-identical across 3 repeated runs after the adapter
// random-fallbacks were stubbed deterministically. Saturated dimensions
// (measured 100) carry floor 100 with margin 0 — in these small owned
// modules any drop means a contract line went untested. Non-saturated
// dimensions carry floor = floor(measured) - 1: with per-file statement
// counts <= ~90, a single lost statement/branch moves the percentage by
// more than a point, so every whole-unit regression trips the gate.
// Never lower a floor merely to obtain green — a conscious contract
// change must edit this table in review.
//
// Exit codes: 0 pass · 1 floor regression or missing module row ·
// 2 malformed/unreadable summary. Machine line: UNIT_COVERAGE v1.
import { readFileSync } from 'node:fs'
import { resolve, sep } from 'node:path'

const METRICS = ['statements', 'branches', 'functions', 'lines']

// module (repo-relative, forward slashes) → floors [stmts, branch, funcs, lines]
export const FLOORS = {
  'src/App.tsx': [84, 65, 86, 83],
  'src/components/ConnectionBadge.tsx': [100, 100, 100, 100],
  'src/components/EventFeed.tsx': [96, 95, 100, 96],
  'src/components/NetworkView2D.tsx': [43, 49, 68, 40],
  'src/components/ViewErrorBoundary.tsx': [100, 100, 100, 100],
  'src/viz3d/adapters.ts': [96, 94, 100, 100],
  'src/viz3d/edgeValidation.ts': [100, 100, 100, 100],
  'src/viz3d/nodeValidation.ts': [100, 100, 100, 100],
  'src/viz3d/useEventQueue.ts': [95, 90, 91, 96],
  'src/viz3d/useSceneStore.ts': [100, 100, 100, 100],
  'src/ws/SimBridgeClient.ts': [96, 88, 100, 97],
}

export function checkCoverage(summary, floors = FLOORS) {
  if (summary === null || typeof summary !== 'object' || Array.isArray(summary)) {
    return { status: 'MALFORMED', failures: ['summary is not an object'] }
  }
  // Normalize absolute Windows/POSIX paths to repo-relative forward-slash
  // keys so the table stays platform-independent.
  const byModule = new Map()
  for (const [key, value] of Object.entries(summary)) {
    if (key === 'total') continue
    const normalized = key.split(sep).join('/').split('/')
    const srcIndex = normalized.lastIndexOf('src')
    if (srcIndex === -1) continue
    byModule.set(normalized.slice(srcIndex).join('/'), value)
  }

  const failures = []
  for (const [module, moduleFloors] of Object.entries(floors)) {
    const row = byModule.get(module)
    if (row === undefined) {
      failures.push(`${module}: MISSING from coverage summary (row cannot silently disappear)`)
      continue
    }
    METRICS.forEach((metric, i) => {
      const pct = row?.[metric]?.pct
      if (typeof pct !== 'number' || Number.isNaN(pct)) {
        failures.push(`${module}: malformed ${metric} entry`)
        return
      }
      if (pct < moduleFloors[i]) {
        failures.push(`${module}: ${metric} ${pct}% < floor ${moduleFloors[i]}%`)
      }
    })
  }
  const malformed = failures.some(f => f.includes('malformed'))
  return {
    status: failures.length === 0 ? 'PASS' : malformed ? 'MALFORMED' : 'FAIL',
    failures,
  }
}

function main() {
  const summaryPath = resolve(process.argv[2] ?? 'coverage/coverage-summary.json')
  let summary
  try {
    summary = JSON.parse(readFileSync(summaryPath, 'utf8'))
  } catch (error) {
    console.error(`UNIT_COVERAGE v1 status=MALFORMED reason=unreadable-summary path=${summaryPath}`)
    console.error(String(error))
    process.exit(2)
  }
  const { status, failures } = checkCoverage(summary)
  for (const failure of failures) console.error(`  ${failure}`)
  console.log(
    `UNIT_COVERAGE v1 modules=${Object.keys(FLOORS).length} failures=${failures.length} status=${status}`,
  )
  if (status === 'MALFORMED') process.exit(2)
  if (status === 'FAIL') process.exit(1)
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split(sep).join('/').split('/').pop())) {
  main()
}
