import { test, expect, Page } from '@playwright/test';
import { waitForApplicationSocket } from './helpers/waitForApplicationSocket';

// Package AN-2 (issue #2 acceptance audit): the Phase-A2 success criterion
// "3D visualization supports 1000+ nodes smoothly" had no verification at
// any scale. This smoke locks the SEMANTIC half in every engine of the
// matrix: a 1,000-node network with 1,500 edges ingests without error,
// the shell stays interactive, the store admits exactly the valid
// records, and view switching still works afterwards.
//
// SCOPE OF CLAIM (deliberate): "supports" here means no crash, no shell
// wedge, full ingestion and continued interactivity under the documented
// bounded pipeline. This is NOT a frame-rate or rendering-quality
// benchmark — no FPS claim is made (headless GPU stacks make FPS numbers
// meaningless in CI).

interface FakeSocketHarness {
  url: string;
  readyState: number;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  _open: () => void;
  _message: (obj: unknown) => void;
}
// The read-only slice of the scene store this spec observes.
interface SceneStoreHandle {
  getState: () => { nodes: unknown[]; edges: unknown[] };
}
type HarnessWindow = Window &
  typeof globalThis & {
    __fakeSockets: FakeSocketHarness[];
    // Guarded accessor for the active application socket: throws a
    // descriptive error instead of dereferencing `undefined` when the
    // registry is empty or the app socket has not been constructed yet
    // (Jack delta-audit #350).
    __activeAppSocket: () => FakeSocketHarness;
    // The store instance the APP actually writes to, stashed once the
    // readiness probe is observed landing on it. A dynamic import() of
    // the store module resolves to a DISTINCT instance per page.evaluate
    // under Vite dev, so the observation poll must read this one proven
    // reference rather than re-importing (Jack delta-audit #350).
    __sceneStore?: SceneStoreHandle;
  };

async function setupPage(page: Page) {
  await page.addInitScript(() => {
    const w = window as HarnessWindow;
    w.__fakeSockets = [];
    class FakeWebSocket {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
      url: string;
      readyState = 0;
      onopen: ((ev: unknown) => void) | null = null;
      onmessage: ((ev: { data: string }) => void) | null = null;
      onclose: ((ev: unknown) => void) | null = null;
      onerror: ((ev: unknown) => void) | null = null;
      constructor(url: string) {
        this.url = url;
        w.__fakeSockets.push(this);
      }
      send() {}
      close() {
        this.readyState = 3;
      }
      _open() {
        this.readyState = 1;
        if (this.onopen) this.onopen({});
      }
      _message(obj: unknown) {
        if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) });
      }
    }
    w.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    w.__activeAppSocket = () => {
      const registry = Array.isArray(w.__fakeSockets) ? w.__fakeSockets : [];
      const appSockets = registry.filter((s) => String(s.url).includes('/ws'));
      const active = appSockets[appSockets.length - 1];
      if (!active) {
        throw new Error(
          `No active application fake socket (registry size ${registry.length}, ` +
            `app-URL sockets ${appSockets.length}) — did the init script install ` +
            `FakeWebSocket before the app loaded?`,
        );
      }
      return active;
    };
  });
  await page.goto('/');
  await expect(page.locator('#root')).toBeVisible();
  await waitForApplicationSocket(page);
}

test('1,000-node network: full ingestion, live shell, working interaction afterwards', async ({ page }) => {
  // Application-owned diagnostics (console.error) AND uncaught page errors
  // are both captured; a crash-free ingestion leaves BOTH empty (Jack
  // delta-audit #350).
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  page.on('pageerror', (err) => {
    pageErrors.push(err.message);
  });
  await setupPage(page);

  // Establish the ingestion pipeline is LIVE and capture the store the
  // app actually writes to, before the functional assertion. Two coupled
  // realities force a bounded readiness HANDSHAKE here rather than a
  // strict single send (both empirically demonstrated on WebKit under the
  // Vite dev server):
  //   1. The store consumer (useEventQueue inside ThreeScene, inside the
  //      R3F canvas root) subscribes only after the lazy 3D view mounts,
  //      the SimBridgeClient does not buffer events (emit drops with no
  //      listeners), and the subscription exposes no external ready
  //      signal — so a single probe sent at canvas-visible is lost (a
  //      strict-single-send variant failed 5/5 on WebKit).
  //   2. A dynamic import() of the store module resolves to a DISTINCT
  //      instance per page.evaluate under Vite dev — so the observation
  //      poll must read the exact instance a write is proven to land on.
  // The handshake re-sends a probe update for n0 — one of the snapshot's
  // own ids, so the final count is unaffected — until it lands, then
  // stashes THAT proven store instance. The functional assertion below is
  // strictly observation-only, and the bulk snapshot is sent exactly once.
  await expect(
    page.getByRole('region', { name: '3D network view' }).locator('canvas'),
  ).toBeVisible();
  // Single-evaluate handshake (its own establishment step, NOT an
  // assertion poll): open the socket, then re-send the n0 probe with
  // short waits until the store reflects it, capturing THAT proven
  // instance on window for the observation poll. All within one evaluate
  // because the stash and the confirming read must share one module
  // resolution (see the context above); returns the attempt count.
  const readinessSends = await page.evaluate(async () => {
    const w = window as HarnessWindow;
    const live = w.__activeAppSocket();
    live._open();
    const mod = (await import('/src/viz3d/useSceneStore.ts')) as { useSceneStore: SceneStoreHandle };
    const store = mod.useSceneStore;
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    for (let attempt = 1; attempt <= 60; attempt++) {
      w.__activeAppSocket()._message({
        type: 'node_update',
        payload: { id: 'n0', position: [0, 0, 0], connections: [], status: 'active' },
      });
      await sleep(50);
      if (store.getState().nodes.length > 0) {
        w.__sceneStore = store;
        return attempt;
      }
    }
    throw new Error('Scene pipeline never went live: the n0 readiness probe did not reach the store');
  });
  expect(readinessSends).toBeGreaterThan(0);

  // Inject the full snapshot EXACTLY ONCE (guarded): 1,000 positioned
  // nodes on a deterministic lattice + 1,500 edges, one network_update.
  await page.evaluate(() => {
    const live = (window as HarnessWindow).__activeAppSocket();
    const nodes = Array.from({ length: 1000 }, (_, i) => ({
      id: `n${i}`,
      position: [(i % 10) * 8, Math.floor((i % 100) / 10) * 8, Math.floor(i / 100) * 8],
      connections: [],
      status: i % 3 === 0 ? 'active' : i % 3 === 1 ? 'inactive' : 'error',
    }));
    const edges = Array.from({ length: 1500 }, (_, i) => ({
      id: `e${i}`,
      source: `n${i % 1000}`,
      target: `n${(i * 7 + 1) % 1000}`,
      strength: (i % 10) / 10,
    }));
    live._message({ type: 'network_update', payload: { nodes, edges } });
  });

  // Ingestion completes and the store admits exactly the valid records.
  // Observation-only poll (no side effects) reading the ONE proven store
  // reference captured above.
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const s = (window as HarnessWindow).__sceneStore!.getState();
          return { nodes: s.nodes.length, edges: s.edges.length };
        }),
      { timeout: 15000 },
    )
    .toEqual({ nodes: 1000, edges: 1500 });

  // Shell alive and interactive AFTER the bulk ingestion.
  await expect(page.getByRole('region', { name: '3D network view' })).toBeVisible();
  await expect(page.getByRole('status').and(page.locator('[aria-atomic="true"]'))).toBeVisible();
  await expect(page.getByRole('log', { name: 'Event feed' })).toBeVisible();
  await page.getByRole('button', { name: '2D View', exact: true }).click();
  await expect(page.getByRole('region', { name: '2D network view' })).toBeVisible();
  await page.getByRole('button', { name: '3D View' }).click();
  await expect(page.getByRole('region', { name: '3D network view' })).toBeVisible();

  // No application diagnostics and no uncaught page errors surfaced during
  // ingestion or the switches — empty on both channels is the no-crash
  // receipt (no FPS/quality claim is made).
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
