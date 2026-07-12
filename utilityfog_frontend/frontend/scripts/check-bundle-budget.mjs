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

// Limits in exact bytes.
// v1 totals baseline (PR #316 build, 2026-07-11): JS raw 979,384 / gzip
// 272,585; CSS 912/483. v2 entry/chunk baseline (Package AG lazy-split
// build, 2026-07-12): entry 155,478/50,405; largest async chunk (3D)
// 826,250/223,083. Policy (unchanged): baseline + 25% headroom, rounded UP
// to the next 16 KiB boundary; 16 KiB floors tiny assets so hash-level
// noise never trips. TOTAL budgets are deliberately KEPT from v1 -- chunk
// splitting must never disguise total growth.
export const BUDGETS = {
  js_raw: 1_228_800,           // 75 x 16 KiB  (~25.5% over v1 baseline)
  js_gzip: 344_064,            // 21 x 16 KiB  (~26.2% over v1 baseline)
  css_raw: 16_384,             // floor
  css_gzip: 16_384,            // floor
  entry_raw: 196_608,          // 12 x 16 KiB  (~26.5% over 155,478)
  entry_gzip: 65_536,          //  4 x 16 KiB  (~30.0% over 50,405)
  largest_async_raw: 1_048_576,   // 64 x 16 KiB (~26.9% over 826,250)
  largest_async_gzip: 294_912,    // 18 x 16 KiB (~32.2% over 223,083)
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

// v2: classify JS assets into synchronous ENTRY scripts (those referenced
// by module <script> tags in the built index.html) and ASYNC chunks
// (everything else). Fails closed on a missing index.html, an index.html
// referencing no entry script, a malformed reference, or a reference to an
// asset absent from the inventory. Duplicate references count once.
export function classifyAssets(distDir, inventory) {
  const indexPath = join(distDir, 'index.html')
  if (!existsSync(indexPath)) {
    throw new Error(`missing built index.html: ${indexPath} (fail closed)`)
  }
  const html = readFileSync(indexPath, 'utf8')
  const refs = [...html.matchAll(/<script[^>]*\ssrc="([^"]+)"/g)].map((m) => m[1])
  const entryNames = new Set()
  for (const ref of refs) {
    // Accepted forms: /assets/x.js · assets/x.js · ./assets/x.js, each
    // optionally with a query string and/or hash fragment. Rejected (fail
    // closed): external origins and protocol-relative URLs, path
    // traversal, non-JS, and anything else — a reference may never escape
    // dist/assets. Decoding is applied to the FILENAME only, purely to
    // re-check for smuggled separators/traversal; the raw name is used
    // for the inventory match.
    if (/^[a-z][a-z0-9+.-]*:/i.test(ref) || ref.startsWith('//')) {
      throw new Error(`external script reference in index.html: ${ref} (fail closed)`)
    }
    const withoutSuffix = ref.split(/[?#]/)[0]
    const match = /^(?:\.?\/)?assets\/([^/\\]+\.js)$/.exec(withoutSuffix)
    if (!match) {
      throw new Error(`malformed script reference in index.html: ${ref} (fail closed)`)
    }
    const name = match[1]
    let decoded = name
    try {
      decoded = decodeURIComponent(name)
    } catch {
      throw new Error(`undecodable script reference in index.html: ${ref} (fail closed)`)
    }
    if (decoded.includes('/') || decoded.includes('\\') || decoded.includes('..')) {
      throw new Error(`traversal in script reference in index.html: ${ref} (fail closed)`)
    }
    entryNames.add(name)
  }
  if (entryNames.size === 0) {
    throw new Error('index.html references no entry script (fail closed)')
  }
  const byName = new Map(inventory.filter((i) => i.kind === 'js').map((i) => [i.name, i]))
  const entries = []
  for (const name of entryNames) {
    const asset = byName.get(name)
    if (!asset) {
      throw new Error(`index.html references a missing asset: ${name} (fail closed)`)
    }
    entries.push(asset)
  }
  const asyncChunks = inventory.filter((i) => i.kind === 'js' && !entryNames.has(i.name))
  // Raw-largest and gzip-largest are tracked INDEPENDENTLY: a chunk that
  // is smaller raw but less compressible can be the gzip maximum, and the
  // gzip budget must bind THAT chunk (audit correction — previously the
  // gzip limit was applied to the raw-largest chunk only).
  let largestAsyncRaw = null
  let largestAsyncGzip = null
  for (const chunk of asyncChunks) {
    if (largestAsyncRaw === null || chunk.raw > largestAsyncRaw.raw) largestAsyncRaw = chunk
    if (largestAsyncGzip === null || chunk.gzip > largestAsyncGzip.gzip) largestAsyncGzip = chunk
  }
  return {
    entry: {
      names: [...entryNames].sort(),
      raw: entries.reduce((n, a) => n + a.raw, 0),
      gzip: entries.reduce((n, a) => n + a.gzip, 0),
    },
    asyncCount: asyncChunks.length,
    largestAsyncRaw,
    largestAsyncGzip,
  }
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
export function checkBudgets(summary, budgets = BUDGETS, classification = null) {
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
  if (classification !== null) {
    checks.push(
      ['entry_raw', classification.entry.raw],
      ['entry_gzip', classification.entry.gzip],
    )
    // A build with no async chunks has no largest-chunk dimension; the
    // entry and total budgets still bound it completely. Raw and gzip
    // maxima are checked against their own maximal chunks.
    if (classification.largestAsyncRaw !== null) {
      checks.push(['largest_async_raw', classification.largestAsyncRaw.raw])
    }
    if (classification.largestAsyncGzip !== null) {
      checks.push(['largest_async_gzip', classification.largestAsyncGzip.gzip])
    }
  }
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
export function machineLine(summary, result, classification = null) {
  const entryPart =
    classification === null
      ? ''
      : `entry_raw=${classification.entry.raw} entry_gzip=${classification.entry.gzip} ` +
        `async_chunks=${classification.asyncCount} ` +
        `largest_async_raw=${classification.largestAsyncRaw?.raw ?? 0} ` +
        `largest_async_raw_chunk=${classification.largestAsyncRaw?.name ?? '-'} ` +
        `largest_async_gzip=${classification.largestAsyncGzip?.gzip ?? 0} ` +
        `largest_async_gzip_chunk=${classification.largestAsyncGzip?.name ?? '-'} `
  return (
    `BUNDLE_BUDGET v2 ` +
    `js_raw=${summary.js.raw} js_gzip=${summary.js.gzip} ` +
    `css_raw=${summary.css.raw} css_gzip=${summary.css.gzip} ` +
    entryPart +
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
  let classification
  try {
    classification = classifyAssets(distDir, inventory)
  } catch (error) {
    console.error(`bundle budget: ${error.message}`)
    process.exit(2)
  }
  const result = checkBudgets(summary, BUDGETS, classification)
  console.log(formatHuman(inventory, summary))
  console.log(
    `  entry (${classification.entry.names.join('+')}): raw=${classification.entry.raw}/${BUDGETS.entry_raw} gzip=${classification.entry.gzip}/${BUDGETS.entry_gzip}`,
  )
  if (classification.largestAsyncRaw !== null) {
    console.log(
      `  largest async raw (${classification.largestAsyncRaw.name}): ${classification.largestAsyncRaw.raw}/${BUDGETS.largest_async_raw}`,
    )
  }
  if (classification.largestAsyncGzip !== null) {
    console.log(
      `  largest async gzip (${classification.largestAsyncGzip.name}): ${classification.largestAsyncGzip.gzip}/${BUDGETS.largest_async_gzip}`,
    )
  }
  console.log(machineLine(summary, result, classification))
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
