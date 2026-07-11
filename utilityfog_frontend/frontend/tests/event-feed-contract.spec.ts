import { test, expect, Page } from '@playwright/test';

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
    w.WebSocket = FakeWebSocket;
  });
  await page.goto('/');
  // The app's client(s) exist once the root renders; the active one is last.
  await expect(page.locator('#root')).toBeVisible();
}

// Inject one already-parsed-shape message on the app's active socket.
const inject = (page: Page, type: string, payload: unknown) =>
  page.evaluate(({ type, payload }) => {
    const w = window as any;
    const appSockets = w.__fakeSockets.filter((s: any) => String(s.url).includes('/ws'));
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
    const w = window as any;
    const appSockets = w.__fakeSockets.filter((s: any) => String(s.url).includes('/ws'));
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
  expect(text.length).toBeLessThanOrEqual(103); // 100 chars + '...'
});

test('script-like payload text renders as text, never as markup', async ({ page }) => {
  await inject(page, 'simulation_event', { msg: '<script>window.__pwned = true<' + '/script><img src=x onerror="window.__pwned2=true">' });
  await expect(entries(page)).toHaveCount(1);
  // Rendered as text: the literal tag text is present…
  await expect(entries(page).first()).toContainText('<script>');
  // …and no element was actually created from the payload.
  expect(await feed(page).locator('script, img').count()).toBe(0);
  expect(await page.evaluate(() => (window as any).__pwned ?? (window as any).__pwned2 ?? null)).toBeNull();
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
