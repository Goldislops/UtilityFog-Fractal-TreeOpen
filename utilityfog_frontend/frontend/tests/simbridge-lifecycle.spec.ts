import { test, expect, Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Typed test-harness surface (no `any`): the in-page fake socket and the
// harness slots this spec pins onto window. Types are erased at runtime, so
// page.evaluate closures may reference them freely.
interface FakeSocketHarness {
  url: string;
  readyState: number;
  sent: string[];
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  _open: () => void;
  _close: () => void;
  _message: (obj: unknown) => void;
  _messageRaw: (raw: string) => void;
}
interface SimClientLike {
  connect: () => void;
  disconnect: () => void;
  on: (event: string, cb: (data?: unknown) => void) => void;
  off: (event: string, cb: (data?: unknown) => void) => void;
  send: (data: unknown) => void;
  readonly isConnected: boolean;
}
interface ExportCapture {
  revoked: string[];
  sequence: string[];
  download: string;
  href: string;
  text: string;
  blob?: Blob;
}
interface LifecycleHarness {
  events: string[];
  payloads: Array<{ channel: string; payload: unknown }>;
  client: SimClientLike;
  sockets: () => FakeSocketHarness[];
  removable?: (p?: unknown) => void;
}
type HarnessWindow = Window &
  typeof globalThis & {
    __fakeSockets: FakeSocketHarness[];
    __throwNextConstruction?: boolean;
    __h: LifecycleHarness;
    __exportCapture: ExportCapture;
    __cap: ExportCapture;
    __pwned?: boolean;
    __pwned2?: boolean;
  };
// ---------------------------------------------------------------------------


// SimBridgeClient lifecycle contract tests.
//
// A deterministic in-page FakeWebSocket replaces window.WebSocket before the
// app loads (so nothing ever dials a real backend), and the client module is
// imported through the Vite dev server inside the browser. The fake fires
// its close callback asynchronously, exactly like real browsers — that async
// gap is what produced the original zombie-reconnect defect, so the fake
// must reproduce it. Reconnect delay is injected (25ms) for determinism; no
// long sleeps.

const TEST_URL = 'ws://lifecycle-test';
const RECONNECT_MS = 25;
// Comfortably past one reconnect delay, far below two app-default delays.
const AFTER_RECONNECT_MS = 4 * RECONNECT_MS;

async function setupHarness(page: Page) {
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
      sent: string[] = [];
      onopen: ((ev: unknown) => void) | null = null;
      onmessage: ((ev: { data: string }) => void) | null = null;
      onclose: ((ev: unknown) => void) | null = null;
      onerror: ((ev: unknown) => void) | null = null;
      constructor(url: string) {
        // Synchronous construction-failure injection (one-shot): throws
        // BEFORE registration, so no instance exists for a failed attempt.
        if (w.__throwNextConstruction) {
          w.__throwNextConstruction = false;
          throw new Error('synthetic construction failure');
        }
        this.url = url;
        w.__fakeSockets.push(this);
      }
      send(data: string) {
        this.sent.push(data);
      }
      close() {
        if (this.readyState === 3) return;
        this.readyState = 3;
        // Real browsers deliver onclose asynchronously after close().
        setTimeout(() => {
          if (this.onclose) this.onclose({});
        }, 0);
      }
      // Test-side helpers (server-driven transitions are synchronous).
      _open() {
        this.readyState = 1;
        if (this.onopen) this.onopen({});
      }
      _close() {
        if (this.readyState === 3) return;
        this.readyState = 3;
        if (this.onclose) this.onclose({});
      }
      _message(obj: unknown) {
        if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) });
      }
      _messageRaw(raw: string) {
        if (this.onmessage) this.onmessage({ data: raw });
      }
    }
    w.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
  });
  await page.goto('/');
  await page.evaluate(async ({ url, delay }) => {
    const w = window as HarnessWindow;
    const mod = await import('/src/ws/SimBridgeClient.ts');
    w.__h = {
      events: [],
      payloads: [],
      client: new mod.SimBridgeClient(url, delay) as SimClientLike,
      sockets: () => w.__fakeSockets.filter((s) => s.url === url),
    };
    w.__h.client.on('connected', () => w.__h.events.push('connected'));
    w.__h.client.on('disconnected', () => w.__h.events.push('disconnected'));
    w.__h.client.on('error', () => w.__h.events.push('error'));
  }, { url: TEST_URL, delay: RECONNECT_MS });
}

const socketCount = (page: Page) =>
  page.evaluate(() => (window as HarnessWindow).__h.sockets().length);
const events = (page: Page) =>
  page.evaluate(() => (window as HarnessWindow).__h.events as string[]);

test.beforeEach(async ({ page }) => {
  await setupHarness(page);
});

test('first connect creates exactly one socket; repeats while CONNECTING/OPEN are idempotent', async ({ page }) => {
  await page.evaluate(() => (window as HarnessWindow).__h.client.connect());
  expect(await socketCount(page)).toBe(1);

  // Repeat while CONNECTING — no second socket.
  await page.evaluate(() => (window as HarnessWindow).__h.client.connect());
  expect(await socketCount(page)).toBe(1);

  // Open, then repeat while OPEN — still no second socket.
  await page.evaluate(() => (window as HarnessWindow).__h.sockets()[0]._open());
  await page.evaluate(() => (window as HarnessWindow).__h.client.connect());
  expect(await socketCount(page)).toBe(1);

  // Open emitted 'connected' exactly once.
  expect(await events(page)).toEqual(['connected']);
});

test('unexpected close emits disconnected and schedules exactly one reconnect', async ({ page }) => {
  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    h.client.connect();
    h.sockets()[0]._open();
    h.sockets()[0]._close(); // server-side drop
  });
  expect(await events(page)).toEqual(['connected', 'disconnected']);

  // Exactly one replacement socket after the injected delay — POLLED for
  // arrival (fixed sleeps flaked under WebKit timer jitter; Package AJ/AK
  // portability audit) — and still exactly one after another full delay
  // (at most one reconnect per close).
  await expect.poll(() => socketCount(page), { timeout: 2000 }).toBe(2);
  await page.waitForTimeout(AFTER_RECONNECT_MS);
  expect(await socketCount(page)).toBe(2);

  // Successful reopen clears pending reconnect state (no third socket).
  await page.evaluate(() => (window as HarnessWindow).__h.sockets()[1]._open());
  await page.waitForTimeout(AFTER_RECONNECT_MS);
  expect(await socketCount(page)).toBe(2);
});

test('intentional disconnect never yields a replacement socket', async ({ page }) => {
  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    h.client.connect();
    h.sockets()[0]._open();
    h.client.disconnect(); // fake delivers its close callback async
  });
  await page.waitForTimeout(AFTER_RECONNECT_MS);
  expect(await socketCount(page)).toBe(1);
  expect(await events(page)).toEqual(['connected', 'disconnected']);
});

test('disconnect clears an already-scheduled reconnect', async ({ page }) => {
  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    h.client.connect();
    h.sockets()[0]._open();
    h.sockets()[0]._close(); // schedules a reconnect...
    h.client.disconnect();   // ...which this must cancel
  });
  await page.waitForTimeout(AFTER_RECONNECT_MS);
  expect(await socketCount(page)).toBe(1);
});

test('explicit connect after disconnect creates a fresh working socket', async ({ page }) => {
  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    h.client.connect();
    h.sockets()[0]._open();
    h.client.disconnect();
  });
  await page.evaluate(() => (window as HarnessWindow).__h.client.connect());
  expect(await socketCount(page)).toBe(2);
  await page.evaluate(() => (window as HarnessWindow).__h.sockets()[1]._open());
  expect(await events(page)).toEqual(['connected', 'disconnected', 'connected']);
  expect(await page.evaluate(() => (window as HarnessWindow).__h.client.isConnected)).toBe(true);
});

test('late callbacks from an obsolete socket cannot affect the current connection', async ({ page }) => {
  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    h.client.connect();
    h.sockets()[0]._open();
    h.sockets()[0]._close(); // drop → reconnect scheduled
  });
  await expect.poll(() => socketCount(page), { timeout: 2000 }).toBe(2);
  await page.evaluate(() => (window as HarnessWindow).__h.sockets()[1]._open());
  const before = await events(page);

  // Fire every callback on the OBSOLETE socket: all must be inert.
  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    const stale = h.sockets()[0];
    if (stale.onopen) stale.onopen({});
    if (stale.onmessage) stale.onmessage({ data: JSON.stringify({ type: 'node_update', payload: { id: 'stale' } }) });
    if (stale.onclose) stale.onclose({});
  });
  await page.waitForTimeout(AFTER_RECONNECT_MS);
  expect(await events(page)).toEqual(before); // no new connected/disconnected
  expect(await socketCount(page)).toBe(2);    // no extra reconnect socket
  expect(await page.evaluate(() => (window as HarnessWindow).__h.client.isConnected)).toBe(true);
});

test('message routing and listener removal remain behaviorally compatible', async ({ page }) => {
  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    for (const ch of ['simulation_event', 'network_update', 'node_update', 'edge_update']) {
      h.client.on(ch, (p: unknown) => h.payloads.push({ channel: ch, payload: p }));
    }
    h.client.connect();
    h.sockets()[0]._open();
    const s = h.sockets()[0];
    s._message({ type: 'simulation_event', payload: { kind: 'tick' } });
    s._message({ type: 'network_update', payload: { nodes: [] } });
    s._message({ type: 'node_update', payload: { id: 'n1' } });
    s._message({ type: 'edge_update', payload: { id: 'e1' } });
  });
  const payloads = await page.evaluate(() => (window as HarnessWindow).__h.payloads);
  expect(payloads.map((p) => p.channel)).toEqual([
    'simulation_event', 'network_update', 'node_update', 'edge_update',
  ]);
  expect(payloads[2].payload).toEqual({ id: 'n1' });

  // off() prevents later delivery.
  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    h.removable = (p: unknown) => h.payloads.push({ channel: 'removable', payload: p });
    h.client.on('node_update', h.removable);
    h.client.off('node_update', h.removable);
    h.sockets()[0]._message({ type: 'node_update', payload: { id: 'n2' } });
  });
  const after = await page.evaluate(() => (window as HarnessWindow).__h.payloads);
  expect(after.filter((p) => p.channel === 'removable')).toHaveLength(0);
});

test('malformed JSON logs a parse error and is never routed; no page error', async ({ page }) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (e) => pageErrors.push(e.message));

  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    h.client.on('node_update', (p: unknown) => h.payloads.push({ channel: 'node_update', payload: p }));
    h.client.connect();
    h.sockets()[0]._open();
    h.sockets()[0]._messageRaw('{this is not json');
  });
  await page.waitForTimeout(50);
  expect(consoleErrors.some((t) => t.includes('Error parsing message'))).toBe(true);
  expect(await page.evaluate(() => (window as HarnessWindow).__h.payloads.length)).toBe(0);
  expect(pageErrors).toHaveLength(0);
});

test('a throwing listener surfaces as a page error and is not mislabelled as a parse error', async ({ page }) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (e) => pageErrors.push(e.message));

  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    h.client.on('node_update', () => { throw new Error('SENTINEL_LISTENER_FAILURE'); });
    h.client.connect();
    h.sockets()[0]._open();
    // Deliver from a timer so the throw leaves the test's own call stack
    // and reaches the page's uncaught-error channel, as it would from a
    // real socket event.
    setTimeout(() => h.sockets()[0]._message({ type: 'node_update', payload: { id: 'n1' } }), 0);
  });
  await page.waitForTimeout(80);
  expect(pageErrors.some((t) => t.includes('SENTINEL_LISTENER_FAILURE'))).toBe(true);
  expect(consoleErrors.filter((t) => t.includes('Error parsing message'))).toHaveLength(0);
});

test('synchronous constructor failure emits one error, retries once, then connects normally', async ({ page }) => {
  await page.evaluate(() => {
    const w = window as HarnessWindow;
    w.__throwNextConstruction = true;
    w.__h.client.connect();
  });
  // The throwing construction registered no instance.
  expect(await socketCount(page)).toBe(0);
  expect(await events(page)).toEqual(['error']);

  // Exactly one scheduled replacement attempt.
  await page.waitForTimeout(AFTER_RECONNECT_MS);
  expect(await socketCount(page)).toBe(1);
  await page.evaluate(() => (window as HarnessWindow).__h.sockets()[0]._open());
  expect(await events(page)).toEqual(['error', 'connected']);

  // No duplicate timers or sockets after another full delay.
  await page.waitForTimeout(AFTER_RECONNECT_MS);
  expect(await socketCount(page)).toBe(1);
});

test('send serializes only while OPEN and is a no-op otherwise', async ({ page }) => {
  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    h.client.connect();
    h.client.send({ early: true }); // CONNECTING — must be a no-op
  });
  expect(await page.evaluate(() => (window as HarnessWindow).__h.sockets()[0].sent)).toEqual([]);

  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    h.sockets()[0]._open();
    h.client.send({ hello: 'world' });
  });
  expect(await page.evaluate(() => (window as HarnessWindow).__h.sockets()[0].sent)).toEqual([
    JSON.stringify({ hello: 'world' }),
  ]);

  await page.evaluate(() => {
    const h = (window as HarnessWindow).__h;
    h.client.disconnect();
    h.client.send({ late: true }); // released socket — no-op
  });
  expect(await page.evaluate(() => (window as HarnessWindow).__h.sockets()[0].sent)).toEqual([
    JSON.stringify({ hello: 'world' }),
  ]);
});
