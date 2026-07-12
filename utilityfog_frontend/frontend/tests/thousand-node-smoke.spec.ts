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
type HarnessWindow = Window & typeof globalThis & { __fakeSockets: FakeSocketHarness[] };

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
  });
  await page.goto('/');
  await expect(page.locator('#root')).toBeVisible();
  await waitForApplicationSocket(page);
}

test('1,000-node network: full ingestion, live shell, working interaction afterwards', async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on('console', m => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  await setupPage(page);

  // The STORE consumer (useEventQueue inside ThreeScene, itself inside
  // the R3F canvas root) subscribes only once the lazy 3D view has fully
  // mounted — and paint-based waits proved FLAKY on a cold dev server.
  // Semantic readiness instead: a single probe update for n0 (one of the
  // snapshot's own ids, so the final count is unaffected) must land in
  // the store, proving the socket→queue→store pipeline is live.
  await expect(
    page.getByRole('region', { name: '3D network view' }).locator('canvas'),
  ).toBeVisible();
  await page.evaluate(() => {
    const w = window as unknown as {
      __fakeSockets: Array<{ url: string; _open: () => void; _message: (o: unknown) => void }>;
    };
    const socks = w.__fakeSockets.filter(s => String(s.url).includes('/ws'));
    const live = socks[socks.length - 1];
    live._open();
  });
  await expect
    .poll(
      () =>
        page.evaluate(async () => {
          const w = window as unknown as {
            __fakeSockets: Array<{ url: string; _message: (o: unknown) => void }>;
          };
          const socks = w.__fakeSockets.filter(s => String(s.url).includes('/ws'));
          socks[socks.length - 1]._message({
            type: 'node_update',
            payload: { id: 'n0', position: [0, 0, 0], connections: [], status: 'active' },
          });
          const mod = (await import('/src/viz3d/useSceneStore.ts')) as {
            useSceneStore: { getState: () => { nodes: unknown[] } };
          };
          return mod.useSceneStore.getState().nodes.length;
        }),
      { timeout: 20000 },
    )
    .toBeGreaterThan(0);

  // Build and inject the snapshot in-page (one network_update message):
  // 1,000 positioned nodes on a deterministic lattice + 1,500 edges.
  await page.evaluate(() => {
    const w = window as unknown as {
      __fakeSockets: Array<{ url: string; _open: () => void; _message: (o: unknown) => void }>;
    };
    const socks = w.__fakeSockets.filter(s => String(s.url).includes('/ws'));
    const live = socks[socks.length - 1];
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

  // Ingestion completes and the store admits exactly the valid records —
  // read through the SAME Vite-served store module the app graph uses.
  await expect
    .poll(
      () =>
        page.evaluate(async () => {
          const mod = (await import('/src/viz3d/useSceneStore.ts')) as {
            useSceneStore: { getState: () => { nodes: unknown[]; edges: unknown[] } };
          };
          const s = mod.useSceneStore.getState();
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

  // No page errors surfaced during ingestion or the switches (the app's
  // own bounded diagnostics are console.error-scoped and would show here;
  // an empty list is the no-crash receipt).
  expect(consoleErrors).toEqual([]);
});
