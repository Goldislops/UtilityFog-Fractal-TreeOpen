#!/usr/bin/env node
// Bundle-budget gate — Node built-ins only (fs, path, zlib, process, url).
//
// Reads a completed Vite build under dist/assets, inventories JS and CSS
// assets, computes per-kind and total raw bytes plus gzip bytes (fixed
// configuration: zlib gzipSync level 9), and fails nonzero when a budget is
// exceeded or when the expected output is missing (fail closed). Emits a
// concise human-readable report plus one stable machine-readable line.
// Never modifies build artifacts. See PERF_NOTES.md for the baseline,
// limits, headroom policy, and update protocol.

import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join, extname } from 'node:path'
import { gzipSync } from 'node:zlib'
import { fileURLToPath } from 'node:url'

// Limits in exact bytes. Baseline (PR #316 build, measured on 2026-07-11):
//   JS  raw 979,384 · gzip 272,585   (single index-*.js chunk)
//   CSS raw     912 · gzip     483   (single index-*.css)
// Policy: baseline + 25% headroom, rounded UP to the next 16 KiB boundary;
// 16 KiB acts as a floor for tiny assets so hash-level noise never trips.
export const BUDGETS = {
  js_raw: 1_228_800,   // 75 × 16 KiB  (~25.5% over baseline)
  js_gzip: 344_064,    // 21 × 16 KiB  (~26.2% over baseline)
  css_raw: 16_384,     // floor
  css_gzip: 16_384,    // floor
}

const KINDS = { '.js': 'js', '.css': 'css' }

// Deterministically ordered inventory of JS/CSS assets in a directory.
// Throws (fail closed) when the directory is missing.
export function inventoryAssets(assetsDir) {
  if (!existsSync(assetsDir)) {
    throw new Error(`missing assets directory: ${assetsDir}`)
  }
  return readdirSync(assetsDir)
    .filter((name) => extname(name) in KINDS)
    .sort() // deterministic order, independent of filesystem enumeration
    .map((name) => {
      const buf = readFileSync(join(assetsDir, name))
      return {
        name,
        kind: KINDS[extname(name)],
        raw: buf.length,
        gzip: gzipSync(buf, { level: 9 }).length,
      }
    })
}

// Per-kind and total aggregation.
export function summarize(inventory) {
  const sum = {
    js: { count: 0, raw: 0, gzip: 0 },
    css: { count: 0, raw: 0, gzip: 0 },
    total: { count: 0, raw: 0, gzip: 0 },
  }
  for (const item of inventory) {
    sum[item.kind].count += 1
    sum[item.kind].raw += item.raw
    sum[item.kind].gzip += item.gzip
    sum.total.count += 1
    sum.total.raw += item.raw
    sum.total.gzip += item.gzip
  }
  return sum
}

// Budget evaluation. Fails closed when no JavaScript asset exists (an empty
// or partial build must not pass silently).
export function checkBudgets(summary, budgets = BUDGETS) {
  const failures = []
  if (summary.js.count === 0) {
    failures.push('no JavaScript assets found in the build output (fail closed)')
  }
  const checks = [
    ['js_raw', summary.js.raw],
    ['js_gzip', summary.js.gzip],
    ['css_raw', summary.css.raw],
    ['css_gzip', summary.css.gzip],
  ]
  for (const [key, actual] of checks) {
    if (actual > budgets[key]) {
      failures.push(`${key} ${actual} bytes exceeds budget ${budgets[key]} bytes`)
    }
  }
  return { pass: failures.length === 0, failures }
}

export function formatHuman(inventory, summary, budgets = BUDGETS) {
  const lines = ['bundle budget report (bytes; gzip = zlib level 9)']
  for (const item of inventory) {
    lines.push(`  ${item.name}  raw=${item.raw}  gzip=${item.gzip}`)
  }
  lines.push(
    `  JS total:  raw=${summary.js.raw}/${budgets.js_raw}  gzip=${summary.js.gzip}/${budgets.js_gzip}`,
    `  CSS total: raw=${summary.css.raw}/${budgets.css_raw}  gzip=${summary.css.gzip}/${budgets.css_gzip}`,
  )
  return lines.join('\n')
}

// One stable machine-readable summary line (space-separated key=value).
export function machineLine(summary, result) {
  return (
    `BUNDLE_BUDGET v1 ` +
    `js_raw=${summary.js.raw} js_gzip=${summary.js.gzip} ` +
    `css_raw=${summary.css.raw} css_gzip=${summary.css.gzip} ` +
    `total_raw=${summary.total.raw} total_gzip=${summary.total.gzip} ` +
    `status=${result.pass ? 'PASS' : 'FAIL'}`
  )
}

function main() {
  const distDir = process.argv[2] || join(process.cwd(), 'dist')
  if (!existsSync(distDir)) {
    console.error(`bundle budget: missing dist directory: ${distDir} (run the build first)`)
    process.exit(2)
  }
  let inventory
  try {
    inventory = inventoryAssets(join(distDir, 'assets'))
  } catch (error) {
    console.error(`bundle budget: ${error.message}`)
    process.exit(2)
  }
  const summary = summarize(inventory)
  const result = checkBudgets(summary)
  console.log(formatHuman(inventory, summary))
  console.log(machineLine(summary, result))
  if (!result.pass) {
    for (const failure of result.failures) {
      console.error(`bundle budget FAIL: ${failure}`)
    }
    process.exit(1)
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main()
}
