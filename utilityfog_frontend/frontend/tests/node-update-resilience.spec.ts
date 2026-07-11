import { test, expect, Page } from '@playwright/test';

// Positionless/malformed node_update resilience (Package N).
//
// Reproduced defect (combined-lab, 2026-07-11): a node_update whose payload
// lacks a valid position reached the renderers and threw
// `node.position is not iterable` (3D InstancedNodes) — unmounting or
// crash-looping the whole tree; the 2D view's draw effect indexes
// node.position and was equally exposed. The fix validates at the two
// ingestion boundaries (scene store + 2D view's own subscription) via
// src/viz3d/nodeValidation.ts. Transport is untouched: invalid
// visualization data must never affect the WebSocket.
//
// The fake WebSocket intercepts ONLY the app's /ws socket and delegates
// everything else (Vite HMR) to the real WebSocket — the Package J lesson.

async function setupPage(page: Page) {
  await page.addInitScript(() => {
    const w = window as any;
    w.__fakeSockets = [];
    class FakeWebSocket {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
      url: string;
      readyState = 0;
      sent: string[] = [];
      onopen: ((ev: unknown) => void) | null = null;
      onmessage: ((ev: { data: string }) => void) | null = null;
      onclose: ((ev: unknown) => void) | null = null;
      onerror: ((ev: unknown) => void) | null = null;
      constructor(url: string) {
        this.url = url;
        w.__fakeSockets.push(this);
      }
      send(data: string) {
        this.sent.push(data);
      }
      close() {
        if (this.readyState === 3) return;
        this.readyState = 3;
        setTimeout(() => {
          if (this.onclose) this.onclose({});
        }, 0);
      }
      _open() {
        this.readyState = 1;
        if (this.onopen) this.onopen({});
      }
      _message(obj: unknown) {
        if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) });
      }
    }
    const RealWebSocket = w.WebSocket;
    w.WebSocket = new Proxy(FakeWebSocket, {
      construct(target, args) {
        const url = String(args[0] ?? '');
        if (url.includes('/ws')) return new target(url);
        return new (RealWebSocket as any)(...args);
      },
    });
  });
  await page.goto('/');
  await expect(page.locator('#root')).toBeVisible();
  await page.evaluate(() => {
    const w = window as any;
    const socks = w.__fakeSockets.filter((s: any) => String(s.url).includes('/ws'));
    socks[socks.length - 1]._open();
  });
}

const inject = (page: Page, type: string, payload: unknown) =>
  page.evaluate(({ type, payload }) => {
    const w = window as any;
    const socks = w.__fakeSockets.filter((s: any) => String(s.url).includes('/ws'));
    socks[socks.length - 1]._message({ type, payload });
  }, { type, payload });

// Inspect and drive the scene store directly through the Vite-served module
// (verified same-instance: the app graph and this import fetch the one URL
// /src/viz3d/useSceneStore.ts). Store-level calls test the validation
// boundary deterministically; socket injections separately prove app
// survival. (The 3D path's rAF-batched useEventQueue delivery is
// timing-dependent under this harness — its crashes are lab-proven to
// arrive through the same store ingestion this spec drives directly.)
const storeNodes = (page: Page) =>
  page.evaluate(async () => {
    const mod = await import('/src/viz3d/useSceneStore.ts');
    return mod.useSceneStore.getState().nodes as Array<{ id: string; position: unknown }>;
  });
const storeUpdate = (page: Page, payload: unknown) =>
  page.evaluate(async (payload) => {
    const mod = await import('/src/viz3d/useSceneStore.ts');
    mod.useSceneStore.getState().updateNode(payload as never);
  }, payload);
const storeSetNetwork = (page: Page, nodes: unknown, edges: unknown) =>
  page.evaluate(async ({ nodes, edges }) => {
    const mod = await import('/src/viz3d/useSceneStore.ts');
    mod.useSceneStore.getState().setNetwork(nodes as never, edges as never);
  }, { nodes, edges });

// NOTE: this branch bases on main, which has no region landmarks (#314 adds
// those) — mounted-ness is asserted structurally.
const appMounted = async (page: Page) => {
  await expect(page.locator('#root')).toBeVisible();
  // The load-bearing assertion: the app container did not unmount.
  await expect(page.locator('.app-container')).toBeVisible();
  await expect(page.getByRole('button', { name: '3D View' })).toBeVisible();
};

const VALID = (id: string, pos: [number, number, number] = [1, 2, 3]) => ({
  id,
  position: pos,
  connections: [],
  status: 'active',
});

test.beforeEach(async ({ page }) => {
  await setupPage(page);
});

test('valid new node renders normally (reaches the store intact)', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await storeUpdate(page, VALID('n-ok', [4, 5, 6]));
  await inject(page, 'node_update', VALID('n-ok-socket', [4, 5, 6])); // survival path
  await page.waitForTimeout(150);
  const nodes = await storeNodes(page);
  expect(nodes.map(n => n.id)).toContain('n-ok');
  expect(nodes.find(n => n.id === 'n-ok')!.position).toEqual([4, 5, 6]);
  await appMounted(page);
  expect(errors).toHaveLength(0);
});

test('existing node + positionless update: no error, last valid position preserved, other fields update', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await storeUpdate(page, VALID('n-keep', [7, 8, 9]));
  await storeUpdate(page, { id: 'n-keep', status: 'error' }); // no position
  await inject(page, 'node_update', { id: 'n-keep', status: 'error' }); // survival path
  await page.waitForTimeout(150);
  const node = (await storeNodes(page)).find(n => n.id === 'n-keep')!;
  expect(node.position).toEqual([7, 8, 9]); // last valid preserved
  expect((node as any).status).toBe('error'); // other fields updated
  await appMounted(page);
  expect(errors).toHaveLength(0);
});

test('unknown node without valid position: app stays mounted, node excluded from rendering source', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await storeUpdate(page, { id: 'n-ghost', status: 'active' });
  await inject(page, 'node_update', { id: 'n-ghost', status: 'active' }); // survival path
  await page.waitForTimeout(200);
  expect((await storeNodes(page)).map(n => n.id)).not.toContain('n-ghost');
  await appMounted(page);
  expect(errors).toHaveLength(0);
});

test('malformed positions never crash: null, string, wrong lengths, non-numbers', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const bad = [
    { id: 'b-null', position: null },
    { id: 'b-str', position: 'up-and-left' },
    { id: 'b-len0', position: [] },
    { id: 'b-len2', position: [1, 2] },
    { id: 'b-len4', position: [1, 2, 3, 4] },
    { id: 'b-nan', position: [1, 'two', 3] },
    { id: 'b-inf', position: [1, 2, Number.POSITIVE_INFINITY] },
  ];
  for (const payload of bad) {
    await storeUpdate(page, payload);
    await inject(page, 'node_update', payload); // survival path
  }
  // A non-object payload for good measure (unidentifiable → dropped).
  await storeUpdate(page, 'not-a-node');
  await inject(page, 'node_update', 'not-a-node');
  await page.waitForTimeout(250);
  const ids = (await storeNodes(page)).map(n => n.id);
  for (const payload of bad) {
    expect(ids).not.toContain(payload.id);
  }
  await appMounted(page);
  expect(errors).toHaveLength(0);
});

test('partial status-only update preserves position AND connections (merge semantics)', async ({ page }) => {
  await storeUpdate(page, { id: 'n-merge', position: [1, 2, 3], connections: ['a', 'b'], status: 'active' });
  await storeUpdate(page, { id: 'n-merge', status: 'error' }); // partial, no position/connections
  const node = (await storeNodes(page)).find(n => n.id === 'n-merge') as any;
  expect(node.position).toEqual([1, 2, 3]);
  expect(node.connections).toEqual(['a', 'b']); // omitted field survives
  expect(node.status).toBe('error');
});

test('valid-position partial update preserves omitted fields', async ({ page }) => {
  await storeUpdate(page, { id: 'n-move', position: [1, 1, 1], connections: ['x'], status: 'active' });
  await storeUpdate(page, { id: 'n-move', position: [9, 9, 9] }); // no connections/status
  const node = (await storeNodes(page)).find(n => n.id === 'n-move') as any;
  expect(node.position).toEqual([9, 9, 9]);
  expect(node.connections).toEqual(['x']);
  expect(node.status).toBe('active');
});

test('unknown node with valid position but missing connections is admitted (renderer-required fields only)', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await storeUpdate(page, { id: 'n-min', position: [2, 2, 2] }); // no connections/status
  await page.waitForTimeout(300); // let the 3D effect render it
  const node = (await storeNodes(page)).find(n => n.id === 'n-min') as any;
  expect(node.position).toEqual([2, 2, 2]);
  expect(errors).toHaveLength(0); // renderers tolerate missing optional fields
  await appMounted(page);
});

test('bulk network_update: null/undefined/primitive payloads never throw', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  for (const payload of [null, undefined, 42, 'garbage', { nodes: null, edges: null }]) {
    await inject(page, 'network_update', payload);
    await storeSetNetwork(page, (payload as any)?.nodes, (payload as any)?.edges);
  }
  await page.waitForTimeout(200);
  await appMounted(page);
  expect(errors).toHaveLength(0);
});

test('bulk per-side tolerance: malformed side never discards the valid side; empty arrays clear', async ({ page }) => {
  await storeSetNetwork(page, [VALID('bulk-1', [1, 1, 1])], [{ id: 'e1', source: 'bulk-1', target: 'bulk-1', strength: 1 }]);
  let nodes = await storeNodes(page);
  expect(nodes.map(n => n.id)).toContain('bulk-1');

  // Malformed nodes side + (implicitly valid) edges side: nodes preserved.
  await storeSetNetwork(page, 'not-an-array', []);
  nodes = await storeNodes(page);
  expect(nodes.map(n => n.id)).toContain('bulk-1'); // valid side kept, edges cleared

  // Valid nodes side + malformed edges side.
  await storeSetNetwork(page, [VALID('bulk-2', [2, 2, 2])], { bogus: true });
  nodes = await storeNodes(page);
  expect(nodes.map(n => n.id)).toContain('bulk-2');

  // Explicit empty arrays clear both collections.
  await storeSetNetwork(page, [], []);
  nodes = await storeNodes(page);
  expect(nodes).toHaveLength(0);
});

test('a later valid update recovers an excluded node', async ({ page }) => {
  await storeUpdate(page, { id: 'n-late', position: [1, 2] }); // invalid → excluded
  expect((await storeNodes(page)).map(n => n.id)).not.toContain('n-late');
  await storeUpdate(page, VALID('n-late', [10, 11, 12]));
  const node = (await storeNodes(page)).find(n => n.id === 'n-late')!;
  expect(node.position).toEqual([10, 11, 12]);
});

test('rapid mixed valid/invalid updates do not duplicate nodes', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.evaluate(async () => {
    const mod = await import('/src/viz3d/useSceneStore.ts');
    const w = window as any;
    const socks = w.__fakeSockets.filter((s: any) => String(s.url).includes('/ws'));
    const s = socks[socks.length - 1];
    for (let n = 0; n < 40; n++) {
      // Alternate valid and invalid updates for the SAME node id, through
      // BOTH the store boundary and the socket survival path.
      const payload = n % 2 === 0
        ? { id: 'n-mixed', position: [n, n, n], connections: [], status: 'active' }
        : { id: 'n-mixed', position: null, status: 'inactive' };
      mod.useSceneStore.getState().updateNode(payload as never);
      s._message({ type: 'node_update', payload });
    }
  });
  await page.waitForTimeout(400); // batched drain (10 per animation frame)
  const nodes = await storeNodes(page);
  expect(nodes.filter(n => n.id === 'n-mixed')).toHaveLength(1);
  // Whatever interleaving landed last, the stored position is a valid triple.
  const pos = nodes.find(n => n.id === 'n-mixed')!.position as number[];
  expect(Array.isArray(pos) && pos.length === 3).toBe(true);
  await appMounted(page);
  expect(errors).toHaveLength(0);
});

test('2D↔3D switching stays functional after malformed bursts (both ingestion paths)', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await storeUpdate(page, VALID('n-2d', [0, 0, 0]));
  await inject(page, 'node_update', { id: 'n-2d-ghost' }); // positionless
  await page.waitForTimeout(150);

  // Switch to 2D — its own subscription must have applied the same contract.
  // (main has no region landmarks; the 2D canvas is the structural witness.)
  await page.getByRole('button', { name: '2D View' }).click();
  await expect(page.locator('.app-container canvas')).toBeVisible();
  // While 2D is mounted its DIRECT subscription ingests these (no rAF queue):
  await inject(page, 'node_update', { id: 'n-2d', position: 'garbage' });
  await inject(page, 'network_update', { nodes: [VALID('n-2d-live', [3, 3, 3]), { id: 'bulk-ghost' }], edges: [] });
  await storeSetNetwork(page, [VALID('n-2d', [3, 3, 3]), { id: 'bulk-ghost' }], []);
  await page.waitForTimeout(200);

  // Back to 3D — still alive.
  await page.getByRole('button', { name: '3D View' }).click();
  await expect(page.locator('.app-container canvas')).toBeVisible();
  const ids = (await storeNodes(page)).map(n => n.id);
  expect(ids).toContain('n-2d');
  expect(ids).not.toContain('bulk-ghost');
  await appMounted(page);
  expect(errors).toHaveLength(0);
});

test('invalid data causes no reconnect and no duplicate socket lineage', async ({ page }) => {
  const before = await page.evaluate(() =>
    (window as any).__fakeSockets.filter((s: any) => String(s.url).includes('/ws')).length);
  for (let i = 0; i < 10; i++) {
    await inject(page, 'node_update', { id: `spam-${i}`, position: null });
  }
  await page.waitForTimeout(400);
  const after = await page.evaluate(() =>
    (window as any).__fakeSockets.filter((s: any) => String(s.url).includes('/ws')).length);
  expect(after).toBe(before); // transport untouched — no reconnect churn
  await appMounted(page);
});

test('no console-error spam from dropped updates; StrictMode delivers once', async ({ page }) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => pageErrors.push(e.message));

  await inject(page, 'node_update', { id: 'quiet-ghost' });
  await inject(page, 'node_update', VALID('n-once', [2, 2, 2]));
  await page.waitForTimeout(200);

  // StrictMode double-mount must not duplicate: exactly one instance in
  // the store boundary, driven directly.
  await storeUpdate(page, VALID('n-once', [2, 2, 2]));
  const nodes = await storeNodes(page);
  expect(nodes.filter(n => n.id === 'n-once')).toHaveLength(1);
  expect(pageErrors).toHaveLength(0);
  expect(consoleErrors.filter(t => !t.includes('WebSocket error'))).toHaveLength(0);
});
