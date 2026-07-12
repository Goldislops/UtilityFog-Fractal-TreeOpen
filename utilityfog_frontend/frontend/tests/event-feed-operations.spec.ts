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


// EventFeed OPERATIONS tests (Package J — filtering, search, summary, clear,
// JSON export). Same in-page FakeWebSocket harness as the contract spec;
// fixed benign JSON fixtures; nothing external.
//
// Serialization-failure note (declared): every payload enters through
// JSON.parse in SimBridgeClient, so no in-page fixture can deliver an
// unserializable payload through the message path — the component's bounded
// export-error guard is therefore untestable from here and is covered by
// code inspection only.

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
      send(data: string) { this.sent.push(data); }
      close() {
        if (this.readyState === 3) return;
        this.readyState = 3;
        setTimeout(() => { if (this.onclose) this.onclose({}); }, 0);
      }
      _open() { this.readyState = 1; if (this.onopen) this.onopen({}); }
      _message(obj: unknown) { if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) }); }
    }
    // Only the app's SimBridge socket (/ws path) is faked; everything else
    // (notably Vite's HMR client socket) keeps the real WebSocket, so the
    // dev-server connection stays healthy and never triggers the client's
    // lost-connection page reload mid-test.
    const RealWebSocket = w.WebSocket;
    w.WebSocket = new Proxy(FakeWebSocket, {
      construct(target, args) {
        const url = String(args[0] ?? '');
        if (url.includes('/ws')) return new target(url);
        return new RealWebSocket(...(args as ConstructorParameters<typeof WebSocket>));
      },
    }) as unknown as typeof WebSocket;
  });
  await page.goto('/');
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

const inject = (page: Page, type: string, payload: unknown) =>
  page.evaluate(({ type, payload }) => {
    const w = window as HarnessWindow;
    const socks = w.__fakeSockets.filter((s) => String(s.url).includes('/ws'));
    socks[socks.length - 1]._message({ type, payload });
  }, { type, payload });

const feed = (page: Page) => page.locator('.event-feed');
const log = (page: Page) => page.getByRole('log', { name: 'Event feed' });
const entries = (page: Page) => log(page).locator('[data-event-channel]');
const summary = (page: Page) => page.getByTestId('feed-summary');
const chan = (page: Page, name: string) => feed(page).getByRole('button', { name, exact: true });
const searchBox = (page: Page) => feed(page).getByLabel('Search events');
const clearBtn = (page: Page) => feed(page).getByRole('button', { name: 'Clear' });
const exportBtn = (page: Page) => feed(page).getByRole('button', { name: 'Export visible JSON' });

const injectFour = async (page: Page) => {
  await inject(page, 'simulation_event', { kind: 'tick' });
  await inject(page, 'network_update', { nodes: [] });
  await inject(page, 'node_update', { id: 'n1', position: [0, 0, 0], connections: [], status: 'active' });
  await inject(page, 'edge_update', { id: 'e1' });
  await expect(entries(page)).toHaveCount(4);
};

// Install export-capture stubs (blob text, anchor download/href, revocations)
const armExportCapture = (page: Page) =>
  page.evaluate(() => {
    const w = window as HarnessWindow;
    // Ordered event sequence proves the download click happens BEFORE the
    // (deferred) revocation — no fixed sleeps; tests poll for 'revoke'.
    w.__exportCapture = { revoked: [], sequence: [], download: '', href: '', text: '' };
    URL.createObjectURL = ((blob: Blob) => {
      w.__exportCapture.blob = blob;
      w.__exportCapture.sequence.push('create');
      return 'blob:capture-1';
    }) as typeof URL.createObjectURL;
    URL.revokeObjectURL = ((u: string) => {
      w.__exportCapture.revoked.push(u);
      w.__exportCapture.sequence.push('revoke');
    }) as typeof URL.revokeObjectURL;
    HTMLAnchorElement.prototype.click = function () {
      w.__exportCapture.download = (this as HTMLAnchorElement).download;
      w.__exportCapture.href = (this as HTMLAnchorElement).href;
      w.__exportCapture.sequence.push('click');
    };
  });
const awaitRevocation = async (page: Page) => {
  await expect
    .poll(async () => page.evaluate(() => (window as HarnessWindow).__exportCapture.revoked.length))
    .toBe(1);
  const seq = await page.evaluate(() => (window as HarnessWindow).__exportCapture.sequence);
  expect(seq.indexOf('click')).toBeGreaterThanOrEqual(0);
  expect(seq.indexOf('click')).toBeLessThan(seq.indexOf('revoke'));
};
const readExport = (page: Page) =>
  page.evaluate(async () => {
    const c = (window as HarnessWindow).__exportCapture;
    return {
      download: c.download,
      href: c.href,
      revoked: c.revoked,
      doc: JSON.parse(await c.blob.text()),
    };
  });

test.beforeEach(async ({ page }) => {
  await setupPage(page);
});

test('initial state: all four channels selected, clear/export disabled, truthful empty summary', async ({ page }) => {
  for (const c of ['simulation_event', 'network_update', 'node_update', 'edge_update']) {
    await expect(chan(page, c)).toHaveAttribute('aria-pressed', 'true');
  }
  await expect(summary(page)).toHaveText('No events retained.');
  await expect(clearBtn(page)).toBeDisabled();
  await expect(exportBtn(page)).toBeDisabled();
  await expect(log(page)).toContainText('No events yet');
});

test('single- and multi-channel filtering changes presentation only', async ({ page }) => {
  await injectFour(page);

  // Single channel: node_update only.
  for (const off of ['simulation_event', 'network_update', 'edge_update']) {
    await chan(page, off).click();
    await expect(chan(page, off)).toHaveAttribute('aria-pressed', 'false');
  }
  await expect(entries(page)).toHaveCount(1);
  await expect(entries(page).first()).toHaveAttribute('data-event-channel', 'node_update');
  await expect(summary(page)).toHaveText('Showing 1 of 4 events');

  // Multi-channel: add edge_update back.
  await chan(page, 'edge_update').click();
  await expect(entries(page)).toHaveCount(2);
  await expect(summary(page)).toHaveText('Showing 2 of 4 events');

  // Hidden events remained retained: re-enable all → all four reappear.
  await chan(page, 'simulation_event').click();
  await chan(page, 'network_update').click();
  await expect(entries(page)).toHaveCount(4);
  await expect(summary(page)).toHaveText('Showing 4 of 4 events');
});

test('every channel disabled: clear empty-filter wording, queue intact', async ({ page }) => {
  await injectFour(page);
  for (const c of ['simulation_event', 'network_update', 'node_update', 'edge_update']) {
    await chan(page, c).click();
  }
  await expect(entries(page)).toHaveCount(0);
  await expect(log(page)).toContainText('No events match the current filters.');
  await expect(summary(page)).toHaveText('Showing 0 of 4 events');
  await expect(exportBtn(page)).toBeDisabled(); // zero visible
  // Queue intact: re-enable one channel and its event returns.
  await chan(page, 'node_update').click();
  await expect(entries(page)).toHaveCount(1);
});

test('search: trimmed, case-insensitive, composes with filters, whitespace is a no-op', async ({ page }) => {
  await injectFour(page);

  await searchBox(page).fill('  NODE_UPD  '); // trimmed + case-insensitive
  await expect(entries(page)).toHaveCount(1);
  await expect(entries(page).first()).toHaveAttribute('data-event-channel', 'node_update');

  await searchBox(page).fill('   '); // whitespace-only → no filtering
  await expect(entries(page)).toHaveCount(4);

  // Composition: search matches two entries' previews, filter removes one.
  await searchBox(page).fill('id');
  await expect(entries(page)).toHaveCount(2); // node n1 + edge e1 previews contain "id"
  await chan(page, 'edge_update').click();
  await expect(entries(page)).toHaveCount(1);
  await expect(entries(page).first()).toHaveAttribute('data-event-channel', 'node_update');
  await expect(summary(page)).toHaveText('Showing 1 of 4 events');

  // Clearing search restores the filter-only view.
  await searchBox(page).fill('');
  await expect(entries(page)).toHaveCount(3); // edge_update still filtered off
});

test('search input treats markup-like queries as plain text', async ({ page }) => {
  await injectFour(page);
  await searchBox(page).fill('<script>alert(1)</script>');
  await expect(entries(page)).toHaveCount(0);
  await expect(log(page)).toContainText('No events match the current filters.');
  expect(await feed(page).locator('script').count()).toBe(0);
});

test('clear empties retained events without breaking later delivery', async ({ page }) => {
  await injectFour(page);
  await expect(clearBtn(page)).toBeEnabled();
  await clearBtn(page).click();
  await expect(summary(page)).toHaveText('No events retained.');
  await expect(log(page)).toContainText('No events yet');
  await expect(clearBtn(page)).toBeDisabled();

  // Subscriptions untouched: a later event still arrives.
  await inject(page, 'edge_update', { id: 'after-clear' });
  await expect(entries(page)).toHaveCount(1);
  await expect(summary(page)).toHaveText('Showing 1 of 1 events');
});

test('the 50-event retained cap holds regardless of filters', async ({ page }) => {
  test.slow(); // 50-entry render under parallel-worker contention
  // Fixture hygiene: the flood uses simulation_event, which the 3D scene
  // store does not consume — bursts of structurally-minimal node_update
  // payloads (no position) can crash the untouched viz3d lane (pre-existing
  // app fragility, reported separately; outside this PR's allowed files).
  for (const off of ['network_update', 'node_update', 'edge_update']) {
    await chan(page, off).click();
  }
  await page.evaluate(() => {
    const w = window as HarnessWindow;
    const socks = w.__fakeSockets.filter((s) => String(s.url).includes('/ws'));
    const s = socks[socks.length - 1];
    for (let n = 1; n <= 55; n++) s._message({ type: 'simulation_event', payload: { seq: `m-${n}` } });
  });
  // Retained queue capped at 50 even though visibility never changed it.
  await expect(summary(page)).toHaveText('Showing 50 of 50 events');
  await expect(entries(page)).toHaveCount(50);
  await expect(entries(page).first()).toContainText('m-55');
  await expect(entries(page).last()).toContainText('m-6');
});

test('export: visible-only, newest-first, schema/version, full payloads, revoked URL, deterministic filename', async ({ page }) => {
  test.slow(); // stub installation + blob readback under contention
  const longText = 'y'.repeat(300);
  await inject(page, 'node_update', { seq: 1, id: 'x1', position: [0, 0, 0], connections: [], status: 'active', blob: longText });
  await inject(page, 'edge_update', { seq: 2 });
  await inject(page, 'node_update', { seq: 3, id: 'x3', position: [0, 0, 0], connections: [], status: 'active' });
  await expect(entries(page)).toHaveCount(3);

  // Filter to node_update + search that matches both node entries.
  for (const off of ['simulation_event', 'network_update', 'edge_update']) {
    await chan(page, off).click();
  }
  await expect(entries(page)).toHaveCount(2);

  await armExportCapture(page);
  await expect(exportBtn(page)).toBeEnabled();
  await exportBtn(page).click();
  const result = await readExport(page);

  expect(result.download).toBe('event-feed-export.json');
  expect(result.href).toBe('blob:capture-1');
  await awaitRevocation(page);
  expect(await page.evaluate(() => (window as HarnessWindow).__exportCapture.revoked)).toContain('blob:capture-1');
  expect(result.doc.schema).toBe('utilityfog.event-feed-export');
  expect(result.doc.version).toBe(1);
  // Visible-only (edge_update excluded), newest first.
  expect(result.doc.events).toHaveLength(2);
  expect(result.doc.events[0].channel).toBe('node_update');
  expect(result.doc.events[0].payload.seq).toBe(3);
  expect(result.doc.events[1].payload.seq).toBe(1);
  // Full untruncated payload — not the 100-char preview.
  expect(result.doc.events[1].payload.blob).toBe(longText);
  expect(result.doc.events[1].payload.blob.length).toBe(300);
  // Timestamps present on every record.
  expect(typeof result.doc.events[0].timestamp).toBe('number');
});

test('export composes with search + filter and is disabled at zero visible', async ({ page }) => {
  await injectFour(page);
  await searchBox(page).fill('no-such-token-xyz');
  await expect(entries(page)).toHaveCount(0);
  await expect(exportBtn(page)).toBeDisabled();

  await searchBox(page).fill('e1'); // edge preview only
  await expect(entries(page)).toHaveCount(1);
  await armExportCapture(page);
  await exportBtn(page).click();
  const result = await readExport(page);
  expect(result.doc.events).toHaveLength(1);
  expect(result.doc.events[0].channel).toBe('edge_update');
  await awaitRevocation(page); // exactly one revocation here too
});

test('export normalizes absent payloads to null and preserves falsy payloads distinctly', async ({ page }) => {
  // Injection order (oldest→newest): absent, null, false, 0, ''.
  await page.evaluate(() => {
    const w = window as HarnessWindow;
    const socks = w.__fakeSockets.filter((s) => String(s.url).includes('/ws'));
    const s = socks[socks.length - 1];
    s._message({ type: 'simulation_event' }); // payload property absent
    s._message({ type: 'simulation_event', payload: null });
    s._message({ type: 'simulation_event', payload: false });
    s._message({ type: 'simulation_event', payload: 0 });
    s._message({ type: 'simulation_event', payload: '' });
  });
  await expect(entries(page)).toHaveCount(5);
  await armExportCapture(page);
  await exportBtn(page).click();
  const result = await readExport(page);
  expect(result.doc.events).toHaveLength(5);
  // Every record carries channel, timestamp AND payload — even when the
  // original payload was absent (normalized to explicit null).
  for (const rec of result.doc.events) {
    expect(Object.prototype.hasOwnProperty.call(rec, 'payload')).toBe(true);
    expect(Object.prototype.hasOwnProperty.call(rec, 'channel')).toBe(true);
    expect(Object.prototype.hasOwnProperty.call(rec, 'timestamp')).toBe(true);
  }
  // Newest first: '', 0, false, null (explicit), null (normalized absent).
  expect(result.doc.events.map((r: { payload: unknown }) => r.payload)).toEqual(['', 0, false, null, null]);
  await awaitRevocation(page);
});

test('StrictMode single delivery holds with operations present; no page errors across a mixed sequence', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));

  await inject(page, 'node_update', { id: 'once-1', position: [0, 0, 0], connections: [], status: 'active' });
  await expect(entries(page)).toHaveCount(1); // one delivery per message

  await chan(page, 'node_update').click();
  await chan(page, 'node_update').click();
  await searchBox(page).fill('once-1');
  await expect(entries(page)).toHaveCount(1);
  await searchBox(page).fill('');
  await clearBtn(page).click();
  await inject(page, 'simulation_event', { later: true });
  await expect(entries(page)).toHaveCount(1);

  expect(errors).toHaveLength(0);
});
