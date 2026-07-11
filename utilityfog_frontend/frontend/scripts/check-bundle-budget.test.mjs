// Unit tests for the bundle-budget gate — node:test + assert, temporary
// directories and synthetic fixtures only. Tests invoke the exported logic
// directly; no console-text grepping.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { gzipSync } from 'node:zlib'
import {
  inventoryAssets,
  summarize,
  checkBudgets,
  machineLine,
} from './check-bundle-budget.mjs'

// Populate a freshly created temp dir; on ANY setup failure the created
// directory is removed before the ORIGINAL error is rethrown (cleanup
// failures never mask it). The io seam exists solely so the failure path
// is testable without OS-specific permission tricks.
export function populateAssets(dir, files, io = { mkdirSync, writeFileSync }) {
  try {
    const assets = join(dir, 'assets')
    io.mkdirSync(assets)
    for (const [name, content] of Object.entries(files)) {
      io.writeFileSync(join(assets, name), content)
    }
    return assets
  } catch (error) {
    try {
      rmSync(dir, { recursive: true, force: true })
    } catch {
      // never mask the original setup error with a cleanup failure
    }
    throw error
  }
}

function makeAssets(files) {
  const dir = mkdtempSync(join(tmpdir(), 'budget-test-'))
  const assets = populateAssets(dir, files)
  return { dir, assets }
}

test('under-budget inventory passes', () => {
  const { dir, assets } = makeAssets({ 'app.js': 'x'.repeat(100), 'app.css': 'y'.repeat(50) })
  try {
    const summary = summarize(inventoryAssets(assets))
    const result = checkBudgets(summary, { js_raw: 1000, js_gzip: 1000, css_raw: 1000, css_gzip: 1000 })
    assert.equal(result.pass, true)
    assert.deepEqual(result.failures, [])
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('exact-limit passes; one byte over fails', () => {
  const content = 'a'.repeat(256)
  const { dir, assets } = makeAssets({ 'app.js': content })
  try {
    const summary = summarize(inventoryAssets(assets))
    const generous = { js_gzip: 10_000, css_raw: 10_000, css_gzip: 10_000 }
    assert.equal(checkBudgets(summary, { ...generous, js_raw: 256 }).pass, true)
    const over = checkBudgets(summary, { ...generous, js_raw: 255 })
    assert.equal(over.pass, false)
    assert.match(over.failures.join(' '), /js_raw 256 bytes exceeds budget 255 bytes/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('aggregates across multiple files per kind', () => {
  const { dir, assets } = makeAssets({
    'a.js': 'x'.repeat(10),
    'b.js': 'x'.repeat(20),
    'a.css': 'y'.repeat(5),
    'b.css': 'y'.repeat(7),
  })
  try {
    const summary = summarize(inventoryAssets(assets))
    assert.equal(summary.js.count, 2)
    assert.equal(summary.js.raw, 30)
    assert.equal(summary.css.raw, 12)
    assert.equal(summary.total.raw, 42)
    assert.equal(summary.total.count, 4)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('inventory order is deterministic (sorted by name)', () => {
  const { dir, assets } = makeAssets({ 'zeta.js': 'z', 'alpha.js': 'a', 'mid.css': 'm' })
  try {
    const names = inventoryAssets(assets).map((i) => i.name)
    assert.deepEqual(names, ['alpha.js', 'mid.css', 'zeta.js'])
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('gzip bytes match zlib level-9 output exactly', () => {
  const content = 'repetitive '.repeat(100)
  const { dir, assets } = makeAssets({ 'app.js': content })
  try {
    const [item] = inventoryAssets(assets)
    assert.equal(item.gzip, gzipSync(Buffer.from(content), { level: 9 }).length)
    assert.equal(item.raw, Buffer.byteLength(content))
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('missing assets directory throws (fail closed)', () => {
  const dir = mkdtempSync(join(tmpdir(), 'budget-test-'))
  try {
    assert.throws(() => inventoryAssets(join(dir, 'assets')), /missing assets directory/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('build with no JavaScript fails closed', () => {
  const { dir, assets } = makeAssets({ 'style.css': 'body{}' })
  try {
    const result = checkBudgets(summarize(inventoryAssets(assets)))
    assert.equal(result.pass, false)
    assert.match(result.failures.join(' '), /no JavaScript assets/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('irrelevant extensions are ignored', () => {
  const { dir, assets } = makeAssets({
    'app.js': 'x',
    'app.js.map': 'not counted',
    'notes.txt': 'not counted',
    'image.svg': 'not counted',
  })
  try {
    const inventory = inventoryAssets(assets)
    assert.deepEqual(inventory.map((i) => i.name), ['app.js'])
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('asset names containing spaces are handled', () => {
  const { dir, assets } = makeAssets({ 'my chunk.js': 'x'.repeat(64) })
  try {
    const [item] = inventoryAssets(assets)
    assert.equal(item.name, 'my chunk.js')
    assert.equal(item.raw, 64)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('setup failure removes the created temp directory and rethrows the original error', () => {
  const dir = mkdtempSync(join(tmpdir(), 'budget-test-'))
  const boom = new Error('synthetic writer failure')
  assert.throws(
    () =>
      populateAssets(dir, { 'app.js': 'x' }, {
        mkdirSync,
        writeFileSync: () => {
          throw boom
        },
      }),
    (e) => e === boom, // the ORIGINAL error, not a cleanup error
  )
  assert.equal(existsSync(dir), false) // leaked directory removed
})

test('machine-readable line has the stable shape', () => {
  const { dir, assets } = makeAssets({ 'app.js': 'x'.repeat(40), 'app.css': 'y'.repeat(9) })
  try {
    const summary = summarize(inventoryAssets(assets))
    const line = machineLine(summary, checkBudgets(summary, { js_raw: 100, js_gzip: 100, css_raw: 100, css_gzip: 100 }))
    assert.match(
      line,
      /^BUNDLE_BUDGET v1 js_raw=\d+ js_gzip=\d+ css_raw=\d+ css_gzip=\d+ total_raw=\d+ total_gzip=\d+ status=(PASS|FAIL)$/,
    )
    assert.match(line, /js_raw=40 /)
    assert.match(line, /css_raw=9 /)
    assert.match(line, /status=PASS$/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
