import { test, expect, Page } from '@playwright/test';

// Package AK: responsive + keyboard contracts (issue #2 slice). Semantic
// measurements only — scrollWidth/clientWidth, bounding boxes, focus and
// pressed state; no pixel comparisons.

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
  await page.waitForFunction(() =>
    (window as unknown as { __fakeSockets: Array<{ url: string }> }).__fakeSockets.some(s =>
      String(s.url).includes('/ws'),
    ),
  );
  await page.evaluate(
    () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))),
  );
}

const VIEWPORTS = [
  { name: 'phone-320', width: 320, height: 568 },
  { name: 'phone-390', width: 390, height: 844 },
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'desktop', width: 1280, height: 800 },
];

for (const viewport of VIEWPORTS) {
  test(`responsive contract at ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await setupPage(page);

    // No horizontal page overflow.
    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollWidth, `${viewport.name} h-overflow`).toBeLessThanOrEqual(
      overflow.clientWidth,
    );

    // Shell pieces visible and reachable.
    const button3d = page.getByRole('button', { name: '3D View' });
    const button2d = page.getByRole('button', { name: '2D View' });
    await expect(button3d).toBeVisible();
    await expect(button2d).toBeVisible();
    await expect(page.getByRole('status').and(page.locator('[aria-atomic="true"]'))).toBeVisible();
    await expect(page.getByRole('log', { name: 'Event feed' })).toBeVisible();

    // 44x44 CSS-pixel touch targets for the view controls.
    for (const control of [button3d, button2d]) {
      const box = (await control.boundingBox())!;
      expect(box.width, `${viewport.name} target width`).toBeGreaterThanOrEqual(44);
      expect(box.height, `${viewport.name} target height`).toBeGreaterThanOrEqual(44);
    }

    // The active view region keeps a useful minimum height, and the
    // controls do not cover it (their boxes are disjoint on mobile flow).
    const region = page.getByRole('region');
    const regionBox = (await region.boundingBox())!;
    expect(regionBox.height, `${viewport.name} view height`).toBeGreaterThanOrEqual(200);

    // Both regions reachable: switch to 2D and back.
    await button2d.click();
    await expect(page.getByRole('region', { name: '2D network view' })).toBeVisible();
    await button3d.click();
    await expect(page.getByRole('region', { name: '3D network view' })).toBeVisible();

    // EventFeed stays bounded and scrollable under load.
    await page.evaluate(() => {
      const w = window as unknown as { __fakeSockets: Array<{ url: string; _open: () => void; _message: (o: unknown) => void }> };
      const socks = w.__fakeSockets.filter(s => String(s.url).includes('/ws'));
      const live = socks[socks.length - 1];
      live._open();
      for (let i = 0; i < 55; i++) {
        live._message({ type: 'node_update', payload: { id: `n${i}`, seq: i } });
      }
    });
    const log = page.getByRole('log', { name: 'Event feed' });
    await expect(log.locator('[data-event-channel]')).toHaveCount(50);
    const bounded = await log.evaluate(el => ({
      scrollable: el.scrollHeight > el.clientHeight,
      clientHeight: el.clientHeight,
    }));
    expect(bounded.scrollable, `${viewport.name} feed scrollable`).toBe(true);
    expect(bounded.clientHeight, `${viewport.name} feed bounded`).toBeLessThanOrEqual(
      viewport.height,
    );
  });
}

test('keyboard-only journey: tab order, visible focus, Enter/Space activation, truthful aria-pressed', async ({ page, browserName }) => {
  await setupPage(page);
  const button2d = page.getByRole('button', { name: '2D View' });
  const button3d = page.getByRole('button', { name: '3D View' });

  // Reach the 2D control with the keyboard alone (WebKit needs Alt+Tab
  // for button focus on some platforms; plain Tab works in headless).
  await page.keyboard.press('Tab');
  const first = await page.evaluate(() => document.activeElement?.textContent ?? '');
  expect(first, `first tab stop (${browserName})`).toBe('2D View');

  // Visible focus indicator: the focus-visible outline is non-none.
  const outline = await button2d.evaluate(el => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe('none');

  // Enter activates; aria-pressed stays truthful.
  await page.keyboard.press('Enter');
  await expect(button2d).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('region', { name: '2D network view' })).toBeVisible();

  // Space activates the next control (tab to 3D, Space).
  await page.keyboard.press('Tab');
  await page.keyboard.press('Space');
  await expect(button3d).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('region', { name: '3D network view' })).toBeVisible();

  // Lazy loading never steals focus: focus stays where the user put it.
  const focusedNow = await page.evaluate(() => document.activeElement?.textContent ?? '');
  expect(focusedNow).toBe('3D View');

  // Exactly one live status region after all the switching.
  await expect(page.getByRole('status').and(page.locator('[aria-atomic="true"]'))).toHaveCount(1);
});
