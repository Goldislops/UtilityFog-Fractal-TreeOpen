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


// EventFeed contract tests.
//
// A deterministic in-page FakeWebSocket replaces window.WebSocket before the
// app loads, so the app's own SimBridgeClient connects to a fake and the
// tests drive the feed by injecting messages on the app's ACTIVE socket.
// (React StrictMode mounts effects twice — the app's live client is the one
// constructed last, so helpers always target the LAST app-URL socket.)
// Fixed benign JSON fixtures only; nothing dials a real backend.

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
    w.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
  });
  await page.goto('/');
  // The app's client(s) exist once the root renders; the active one is last.
  await expect(page.locator('#root')).toBeVisible();
  // Portability (Package AJ): waiting for #root alone raced the
  // subscription effects — Chromium happened to win the race, WebKit lost
  // it (events emitted before EventFeed subscribed were silently missed).
  // Semantic readiness: the app socket must exist AND two paint ticks must
  // pass so the post-commit subscription effects have flushed, in every
  // engine.
  await page.waitForFunction(() =>
    (window as unknown as { __fakeSockets: Array<{ url: string }> }).__fakeSockets.some(s =>
      String(s.url).includes('/ws'),
    ),
  );
  await page.evaluate(
    () =>
      new Promise(resolve =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
}

// Inject one already-parsed-shape message on the app's active socket.
const inject = (page: Page, type: string, payload: unknown) =>
  page.evaluate(({ type, payload }) => {
    const w = window as HarnessWindow;
    const appSockets = w.__fakeSockets.filter((s) => String(s.url).includes('/ws'));
    const active = appSockets[appSockets.length - 1];
    active._message({ type, payload });
  }, { type, payload });

const feed = (page: Page) => page.getByRole('log', { name: 'Event feed' });
const entries = (page: Page) => feed(page).locator('[data-event-channel]');

test.beforeEach(async ({ page }) => {
  await setupPage(page);
});

test('initial state shows the empty-feed message and an accessible log', async ({ page }) => {
  await expect(feed(page)).toBeAttached();
  await expect(feed(page)).toContainText('No events yet');
  await expect(entries(page)).toHaveCount(0);
});

test('each channel is labelled by its subscription channel even when the payload has no type', async ({ page }) => {
  await inject(page, 'simulation_event', { kind: 'tick' });
  await inject(page, 'network_update', { nodes: [] });
  await inject(page, 'node_update', { id: 'n1' });
  await inject(page, 'edge_update', { id: 'e1' });

  await expect(entries(page)).toHaveCount(4);
  for (const channel of ['simulation_event', 'network_update', 'node_update', 'edge_update']) {
    await expect(feed(page).locator(`[data-event-channel="${channel}"]`)).toHaveCount(1);
    await expect(feed(page).locator(`[data-event-channel="${channel}"]`)).toContainText(channel);
  }
});

test('a payload-provided type cannot spoof the subscribed channel label', async ({ page }) => {
  await inject(page, 'node_update', { type: 'simulation_event', id: 'sneaky' });
  await expect(entries(page)).toHaveCount(1);
  const entry = entries(page).first();
  await expect(entry).toHaveAttribute('data-event-channel', 'node_update');
  // The label span shows the channel, not the payload's claimed type.
  await expect(entry.locator('span').first()).toHaveText('node_update');
});

test('newest event appears first', async ({ page }) => {
  await inject(page, 'node_update', { marker: 'older' });
  await inject(page, 'edge_update', { marker: 'newer' });
  await expect(entries(page)).toHaveCount(2);
  await expect(entries(page).first()).toHaveAttribute('data-event-channel', 'edge_update');
  await expect(entries(page).last()).toHaveAttribute('data-event-channel', 'node_update');
});

test('exactly fifty events are retained; after fifty-five the oldest five are gone', async ({ page }) => {
  await page.evaluate(() => {
    const w = window as HarnessWindow;
    const appSockets = w.__fakeSockets.filter((s) => String(s.url).includes('/ws'));
    const active = appSockets[appSockets.length - 1];
    for (let n = 1; n <= 55; n++) {
      active._message({ type: 'node_update', payload: { seq: `marker-${n}` } });
    }
  });
  await expect(entries(page)).toHaveCount(50);
  // Newest first…
  await expect(entries(page).first()).toContainText('marker-55');
  // …oldest retained is #6; #1–#5 expired.
  await expect(entries(page).last()).toContainText('marker-6');
  for (const gone of [1, 2, 3, 4, 5]) {
    await expect(feed(page).getByText(`marker-${gone}"`, { exact: false })).toHaveCount(0);
  }
});

test('payload preview is bounded with an ellipsis', async ({ page }) => {
  await inject(page, 'simulation_event', { blob: 'x'.repeat(500) });
  const preview = entries(page).first().locator('div').last();
  const text = (await preview.textContent()) ?? '';
  expect(text.endsWith('...')).toBe(true);
  expect(text.length).toBe(103); // exactly 100 rendered chars + '...'
});

test('nested objects serialize compactly — no whitespace spent on formatting', async ({ page }) => {
  await inject(page, 'simulation_event', { a: { b: [1, 2] } });
  const text = (await entries(page).first().locator('div').last().textContent()) ?? '';
  expect(text).toBe('{"a":{"b":[1,2]}}');
});

test('a compact serialization of exactly 100 characters is shown whole, no ellipsis', async ({ page }) => {
  // {"s":"…"} wrapper is 8 chars; 92 x's → exactly 100.
  await inject(page, 'simulation_event', { s: 'x'.repeat(92) });
  const text = (await entries(page).first().locator('div').last().textContent()) ?? '';
  expect(text.length).toBe(100);
  expect(text.endsWith('...')).toBe(false);
  expect(text).toBe(`{"s":"${'x'.repeat(92)}"}`);
});

test('101 characters truncates to 100 plus exactly one ellipsis', async ({ page }) => {
  await inject(page, 'simulation_event', { s: 'x'.repeat(93) }); // 101 compact chars
  const text = (await entries(page).first().locator('div').last().textContent()) ?? '';
  expect(text.length).toBe(103);
  expect(text.endsWith('...')).toBe(true);
  expect(text.endsWith('....')).toBe(false);
});

test('string payloads remain JSON-quoted (locked contract)', async ({ page }) => {
  await inject(page, 'node_update', 'plain-string');
  const text = (await entries(page).first().locator('div').last().textContent()) ?? '';
  expect(text).toBe('"plain-string"');
});

test('script-like payload text renders as text, never as markup', async ({ page }) => {
  await inject(page, 'simulation_event', { msg: '<script>window.__pwned = true<' + '/script><img src=x onerror="window.__pwned2=true">' });
  await expect(entries(page)).toHaveCount(1);
  // Rendered as text: the literal tag text is present…
  await expect(entries(page).first()).toContainText('<script>');
  // …and no element was actually created from the payload.
  expect(await feed(page).locator('script, img').count()).toBe(0);
  expect(await page.evaluate(() => (window as HarnessWindow).__pwned ?? (window as HarnessWindow).__pwned2 ?? null)).toBeNull();
});

test('StrictMode double-mount does not duplicate entries (cleanup removes listeners)', async ({ page }) => {
  // main.tsx renders in React.StrictMode: effects run setup→cleanup→setup.
  // If unsubscription were broken, one injected message would render twice.
  await inject(page, 'node_update', { once: true });
  await expect(entries(page)).toHaveCount(1);
});

test('no page-level JavaScript errors during a mixed sequence', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await inject(page, 'simulation_event', { kind: 'tick' });
  await inject(page, 'node_update', { type: 'spoof' });
  await inject(page, 'edge_update', { id: 'e9' });
  await expect(entries(page)).toHaveCount(3);
  expect(errors).toHaveLength(0);
});
