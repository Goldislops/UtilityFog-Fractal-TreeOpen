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


// ConnectionBadge accessibility + reduced-motion tests.
//
// A deterministic in-page FakeWebSocket replaces window.WebSocket before the
// app loads; connection transitions are driven on the app's ACTIVE socket
// (React StrictMode mounts effects twice — the live client is the one
// constructed last, so helpers target the LAST app-URL socket). Nothing
// dials a real backend.

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
      _close() {
        if (this.readyState === 3) return;
        this.readyState = 3;
        if (this.onclose) this.onclose({});
      }
    }
    w.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
  });
  await page.goto('/');
  await expect(page.locator('#root')).toBeVisible();
}

const activeSocket = (page: Page, action: '_open' | '_close') =>
  page.evaluate((act) => {
    const w = window as HarnessWindow;
    // Defensive diagnostics: tolerate a missing registry, then fail with a
    // descriptive error rather than an opaque undefined-property throw.
    const registry = Array.isArray(w.__fakeSockets) ? w.__fakeSockets : [];
    const appSockets = registry.filter((s) => String(s.url).includes('/ws'));
    const active = appSockets[appSockets.length - 1];
    if (!active) {
      throw new Error(
        `No active application fake socket (registry size ${registry.length}, ` +
        `app-URL sockets ${appSockets.length}) — did the init script install ` +
        `FakeWebSocket before the app loaded?`
      );
    }
    active[act]();
  }, action);

// The badge's live region specifically: lazy view delivery (Package AG)
// shows a TRANSIENT role=status loading indicator inside the view region,
// so the badge is disambiguated by its aria-atomic contract.
const status = (page: Page) => page.getByRole('status').and(page.locator('[aria-atomic="true"]'))
const dot = (page: Page) => page.locator('.connection-badge [aria-hidden="true"]');
const dotAnimation = (page: Page) =>
  dot(page).evaluate((el) => getComputedStyle(el).animationName);
const statusBackground = (page: Page) =>
  status(page).evaluate((el) => getComputedStyle(el).backgroundColor);

test.beforeEach(async ({ page }) => {
  await setupPage(page);
});

test('connection state is exposed through a status live region across open/close', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));

  // Initial: Disconnected, exposed via role=status, atomic.
  await expect(status(page)).toHaveCount(1);
  await expect(status(page)).toHaveText('Disconnected');
  await expect(status(page)).toHaveAttribute('aria-atomic', 'true');
  expect(await statusBackground(page)).toBe('rgb(239, 68, 68)');

  // Simulated open → Connected (text atomic: exactly the one state string).
  await activeSocket(page, '_open');
  await expect(status(page)).toHaveText('Connected');
  await expect(status(page)).toHaveCount(1);
  expect(await statusBackground(page)).toBe('rgb(16, 185, 129)');

  // Simulated close → back to Disconnected.
  await activeSocket(page, '_close');
  await expect(status(page)).toHaveText('Disconnected');
  expect(await statusBackground(page)).toBe('rgb(239, 68, 68)');

  expect(errors).toHaveLength(0);
});

test('decorative dot is hidden from accessibility APIs', async ({ page }) => {
  await expect(dot(page)).toHaveCount(1);
  await expect(dot(page)).toHaveAttribute('aria-hidden', 'true');
  // The status text is the badge's entire accessible content.
  await expect(status(page)).toHaveText('Disconnected');
});

test('normal motion: pulse animates only while connected', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });

  // Disconnected: no pulse.
  expect(await dotAnimation(page)).toBe('none');

  // Connected: pulse.
  await activeSocket(page, '_open');
  await expect(status(page)).toHaveText('Connected');
  expect(await dotAnimation(page)).toBe('pulse');

  // Disconnected again: pulse stops.
  await activeSocket(page, '_close');
  await expect(status(page)).toHaveText('Disconnected');
  expect(await dotAnimation(page)).toBe('none');
});

test('reduced motion: pulse is suppressed even while connected', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });

  await activeSocket(page, '_open');
  await expect(status(page)).toHaveText('Connected');
  expect(await dotAnimation(page)).toBe('none');

  // Visible wording and colour are unchanged by the media preference.
  expect(await statusBackground(page)).toBe('rgb(16, 185, 129)');
});
