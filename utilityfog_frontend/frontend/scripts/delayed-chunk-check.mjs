#!/usr/bin/env node
// Package AG lab receipt: serve the BUILT app (vite preview) and delay the
// async 3D chunk at the network layer — the shell must be interactive and
// the accessible loading status visible while the chunk is in flight, and
// the view must arrive once it lands. Run manually / in the lab:
//   node scripts/delayed-chunk-check.mjs
// Not wired into CI (spawns a server + real browser).
import { spawn } from 'node:child_process'
import { chromium } from '@playwright/test'

const PORT = 4199
const DELAY_MS = 1500

const server = spawn('npx', ['vite', 'preview', '--port', String(PORT), '--strictPort'], {
  shell: true,
  stdio: 'pipe',
})
const kill = () => {
  // shell:true wraps the server in a shell: killing only server.pid leaves
  // the node child alive holding esbuild/rollup binaries (observed live —
  // it broke a later npm ci with EPERM). Kill the whole tree on Windows;
  // elsewhere the direct kill suffices for vite preview.
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/PID', String(server.pid), '/T', '/F'], { shell: true })
    } else {
      process.kill(server.pid)
    }
  } catch {
    /* already gone */
  }
}

try {
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('preview server timeout')), 15000)
    server.stdout.on('data', d => {
      if (String(d).includes(String(PORT))) {
        clearTimeout(timer)
        resolve()
      }
    })
    server.on('exit', () => reject(new Error('preview server exited early')))
  })

  const browser = await chromium.launch()
  const page = await browser.newPage()
  let chunkDelayed = false
  await page.route('**/assets/NetworkView3D*.js', async route => {
    chunkDelayed = true
    await new Promise(r => setTimeout(r, DELAY_MS))
    await route.continue()
  })

  const t0 = Date.now()
  await page.goto(`http://localhost:${PORT}/`)
  // Shell interactive + accessible loading status WHILE the chunk is delayed.
  await page.getByRole('button', { name: '3D View' }).waitFor({ timeout: DELAY_MS - 300 })
  await page
    .getByText('Loading 3D network view…')
    .waitFor({ timeout: DELAY_MS - 300 })
  const shellVisibleAt = Date.now() - t0
  // The view arrives after the delayed chunk lands (canvas mounted).
  await page.locator('canvas').waitFor({ timeout: DELAY_MS + 15000 })
  const viewVisibleAt = Date.now() - t0

  console.log(
    `DELAYED_CHUNK_CHECK v1 delayed=${chunkDelayed} shell_ms=${shellVisibleAt} view_ms=${viewVisibleAt} status=PASS`,
  )
  await browser.close()
  kill()
  process.exit(0)
} catch (error) {
  console.error('DELAYED_CHUNK_CHECK v1 status=FAIL')
  console.error(error)
  kill()
  process.exit(1)
}
