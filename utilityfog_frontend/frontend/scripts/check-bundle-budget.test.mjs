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
  classifyAssets,
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
      /^BUNDLE_BUDGET v2 js_raw=\d+ js_gzip=\d+ css_raw=\d+ css_gzip=\d+ total_raw=\d+ total_gzip=\d+ status=(PASS|FAIL)$/,
    )
    assert.match(line, /js_raw=40 /)
    assert.match(line, /css_raw=9 /)
    assert.match(line, /status=PASS$/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

// ---------------------------------------------------------------------------
// v2: entry/chunk classification and budgets (Package AH).

function v2Fixture(files, indexHtml) {
  const dir = mkdtempSync(join(tmpdir(), 'budget-v2-'))
  populateAssets(dir, files)
  if (indexHtml !== null) writeFileSync(join(dir, 'index.html'), indexHtml)
  return dir
}
const INDEX = (names) =>
  '<!doctype html><html><head>' +
  names.map((n) => `<script type="module" crossorigin src="/assets/${n}"></script>`).join('') +
  '</head><body></body></html>'

test('v2: single-chunk build classifies as entry-only (no async dimension)', () => {
  const dir = v2Fixture({ 'index-abc.js': 'x'.repeat(100) }, INDEX(['index-abc.js']))
  try {
    const inv = inventoryAssets(join(dir, 'assets'))
    const c = classifyAssets(dir, inv)
    assert.deepEqual(c.entry.names, ['index-abc.js'])
    assert.equal(c.entry.raw, 100)
    assert.equal(c.asyncCount, 0)
    assert.equal(c.largestAsyncRaw, null)
    assert.equal(c.largestAsyncGzip, null)
    const result = checkBudgets(summarize(inv), undefined, c)
    assert.equal(result.pass, true)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('v2: several async chunks — largest identified by raw size', () => {
  const dir = v2Fixture(
    {
      'index-e.js': 'e'.repeat(50),
      'chunk-a.js': 'a'.repeat(200),
      'chunk-b.js': 'b'.repeat(900),
      'chunk-c.js': 'c'.repeat(400),
    },
    INDEX(['index-e.js']),
  )
  try {
    const c = classifyAssets(dir, inventoryAssets(join(dir, 'assets')))
    assert.equal(c.asyncCount, 3)
    assert.equal(c.largestAsyncRaw.name, 'chunk-b.js')
    assert.equal(c.largestAsyncRaw.raw, 900)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('v2: missing index.html fails closed', () => {
  const dir = v2Fixture({ 'index-e.js': 'e' }, null)
  try {
    assert.throws(
      () => classifyAssets(dir, inventoryAssets(join(dir, 'assets'))),
      /missing built index\.html/,
    )
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('v2: index.html referencing a missing entry asset fails closed', () => {
  const dir = v2Fixture({ 'chunk-a.js': 'a' }, INDEX(['index-gone.js']))
  try {
    assert.throws(
      () => classifyAssets(dir, inventoryAssets(join(dir, 'assets'))),
      /references a missing asset: index-gone\.js/,
    )
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('v2: malformed script references fail closed', () => {
  const dir = v2Fixture(
    { 'index-e.js': 'e' },
    '<script type="module" src="http://evil.example/outside.js"></script>',
  )
  try {
    assert.throws(
      () => classifyAssets(dir, inventoryAssets(join(dir, 'assets'))),
      /external script reference/,
    )
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('v2: index.html with no script reference at all fails closed', () => {
  const dir = v2Fixture({ 'index-e.js': 'e' }, '<!doctype html><html><body></body></html>')
  try {
    assert.throws(
      () => classifyAssets(dir, inventoryAssets(join(dir, 'assets'))),
      /references no entry script/,
    )
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('v2: duplicate references to the same entry count once', () => {
  const dir = v2Fixture(
    { 'index-e.js': 'e'.repeat(60) },
    INDEX(['index-e.js', 'index-e.js']),
  )
  try {
    const c = classifyAssets(dir, inventoryAssets(join(dir, 'assets')))
    assert.deepEqual(c.entry.names, ['index-e.js'])
    assert.equal(c.entry.raw, 60)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('v2: windows/posix path handling — classification works from a backslash dist path', () => {
  const dir = v2Fixture({ 'index-e.js': 'e' }, INDEX(['index-e.js']))
  try {
    // join() produced the platform path; feeding an explicitly
    // forward-slashed variant must classify identically (the HTML refs are
    // always forward-slash).
    const alt = dir.split('\\').join('/')
    const c = classifyAssets(alt, inventoryAssets(join(dir, 'assets')))
    assert.deepEqual(c.entry.names, ['index-e.js'])
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('v2: exact limit passes and limit+1 fails, for entry and largest-async budgets', () => {
  const budgets = {
    js_raw: 10_000, js_gzip: 10_000, css_raw: 10_000, css_gzip: 10_000,
    entry_raw: 100, entry_gzip: 10_000, largest_async_raw: 200, largest_async_gzip: 10_000,
  }
  const mk = (entryBytes, chunkBytes) => {
    const dir = v2Fixture(
      { 'index-e.js': 'e'.repeat(entryBytes), 'chunk-a.js': 'a'.repeat(chunkBytes) },
      INDEX(['index-e.js']),
    )
    const inv = inventoryAssets(join(dir, 'assets'))
    const result = checkBudgets(summarize(inv), budgets, classifyAssets(dir, inv))
    rmSync(dir, { recursive: true, force: true })
    return result
  }
  assert.equal(mk(100, 200).pass, true)   // both exactly at limit
  const overEntry = mk(101, 200)
  assert.equal(overEntry.pass, false)
  assert.match(overEntry.failures.join(';'), /entry_raw 101 bytes exceeds budget 100/)
  const overChunk = mk(100, 201)
  assert.equal(overChunk.pass, false)
  assert.match(overChunk.failures.join(';'), /largest_async_raw 201 bytes exceeds budget 200/)
})

test('v2: machine line is stable, versioned and carries the chunk dimensions', () => {
  const dir = v2Fixture(
    { 'index-e.js': 'e'.repeat(10), 'chunk-a.js': 'a'.repeat(20) },
    INDEX(['index-e.js']),
  )
  try {
    const inv = inventoryAssets(join(dir, 'assets'))
    const c = classifyAssets(dir, inv)
    const line = machineLine(summarize(inv), { pass: true }, c)
    assert.match(
      line,
      /^BUNDLE_BUDGET v2 js_raw=\d+ js_gzip=\d+ css_raw=\d+ css_gzip=\d+ entry_raw=10 entry_gzip=\d+ async_chunks=1 largest_async_raw=20 largest_async_raw_chunk=chunk-a\.js largest_async_gzip=\d+ largest_async_gzip_chunk=chunk-a\.js total_raw=\d+ total_gzip=\d+ status=PASS$/,
    )
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('v2: gzip settings are deterministic (same bytes, same gzip size, twice)', () => {
  const content = 'const x = 1;\n'.repeat(500)
  const a = gzipSync(Buffer.from(content), { level: 9 }).length
  const b = gzipSync(Buffer.from(content), { level: 9 }).length
  assert.equal(a, b)
  const dir1 = v2Fixture({ 'index-e.js': content }, INDEX(['index-e.js']))
  const dir2 = v2Fixture({ 'index-e.js': content }, INDEX(['index-e.js']))
  try {
    const g1 = inventoryAssets(join(dir1, 'assets'))[0].gzip
    const g2 = inventoryAssets(join(dir2, 'assets'))[0].gzip
    assert.equal(g1, g2)
  } finally {
    rmSync(dir1, { recursive: true, force: true })
    rmSync(dir2, { recursive: true, force: true })
  }
})

test('v2 audit: accepted reference forms — relative, dot-relative, query and hash', () => {
  for (const form of ['/assets/index-e.js', 'assets/index-e.js', './assets/index-e.js', '/assets/index-e.js?v=1', 'assets/index-e.js#frag', './assets/index-e.js?v=1#frag']) {
    const dir = v2Fixture({ 'index-e.js': 'e' }, `<script type="module" src="${form}"></script>`)
    try {
      const c = classifyAssets(dir, inventoryAssets(join(dir, 'assets')))
      assert.deepEqual(c.entry.names, ['index-e.js'], form)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  }
})

test('v2 audit: rejected reference forms — external origins, traversal, non-JS, protocol-relative', () => {
  const cases = [
    ['http://evil.example/assets/x.js', /external/],
    ['https://evil.example/assets/x.js', /external/],
    ['//evil.example/assets/x.js', /external/],
    ['/assets/../secrets.js', /malformed|traversal/],
    ['/assets/x.css', /malformed/],
    ['/other/x.js', /malformed/],
    ['/assets/%2e%2e.js', /traversal/],
  ]
  for (const [form, expected] of cases) {
    const dir = v2Fixture({ 'index-e.js': 'e' }, `<script type="module" src="${form}"></script>`)
    try {
      assert.throws(() => classifyAssets(dir, inventoryAssets(join(dir, 'assets'))), expected, form)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  }
})

test('v2 audit: gzip budget binds the GZIP-largest chunk, not the raw-largest', () => {
  // A: raw-largest but hugely compressible. B: smaller raw, incompressible
  // — the gzip maximum, and over the gzip budget. The gate must fail on B.
  let seed = 99
  const rand = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648
  let noise = ''
  for (let i = 0; i < 3000; i++) noise += String.fromCharCode(33 + Math.floor(rand() * 90))
  const dir = v2Fixture(
    { 'index-e.js': 'e', 'chunk-a.js': 'a'.repeat(10000), 'chunk-b.js': noise },
    INDEX(['index-e.js']),
  )
  try {
    const inv = inventoryAssets(join(dir, 'assets'))
    const c = classifyAssets(dir, inv)
    assert.equal(c.largestAsyncRaw.name, 'chunk-a.js')
    assert.equal(c.largestAsyncGzip.name, 'chunk-b.js')
    assert.ok(c.largestAsyncGzip.gzip > c.largestAsyncRaw.gzip, 'B must be the gzip max')
    const budgets = {
      js_raw: 1_000_000, js_gzip: 1_000_000, css_raw: 1_000_000, css_gzip: 1_000_000,
      entry_raw: 1_000_000, entry_gzip: 1_000_000,
      largest_async_raw: 1_000_000,
      largest_async_gzip: 1_000, // under B's gzip, above A's
    }
    assert.ok(c.largestAsyncRaw.gzip < 1_000, 'A gzip must be under the budget')
    const result = checkBudgets(summarize(inv), budgets, c)
    assert.equal(result.pass, false)
    assert.match(result.failures.join(';'), /largest_async_gzip \d+ bytes exceeds budget 1000/)
    // The machine line names BOTH maxima distinctly.
    const line = machineLine(summarize(inv), result, c)
    assert.match(line, /largest_async_raw_chunk=chunk-a\.js/)
    assert.match(line, /largest_async_gzip_chunk=chunk-b\.js/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
