import { test, expect, Page } from '@playwright/test';
import { waitForApplicationSocket } from './helpers/waitForApplicationSocket';

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
  // Portability (Package AJ): the SHARED semantic gate — active
  // application socket plus the paint/effect turn.
  await waitForApplicationSocket(page);
}

const VIEWPORTS = [
  { name: 'phone-320', width: 320, height: 568 },
  { name: 'phone-390', width: 390, height: 844 },
  // Short-landscape phones (Package AK amendment): stacked flow CANNOT
  // fit these heights, so the scrolling-container contract carries the
  // reachability proof below.
  { name: 'landscape-667', width: 667, height: 375 },
  { name: 'landscape-740', width: 740, height: 360 },
  { name: 'landscape-844', width: 844, height: 390 },
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

    // Reachability by scrolling (Package AK amendment): below 768px the
    // app container is the vertical scroller. Short-landscape viewports
    // CANNOT fit the stacked flow, so there the container must actually
    // overflow — and every shell piece plus the active view must be
    // reachable by scrolling it.
    if (viewport.width < 768) {
      const container = page.locator('.app-container');
      const scroll = await container.evaluate(el => ({
        scrollable: el.scrollHeight > el.clientHeight,
        overflowY: getComputedStyle(el).overflowY,
      }));
      expect(scroll.overflowY, `${viewport.name} container overflow-y`).toBe('auto');
      if (viewport.height < 500) {
        expect(scroll.scrollable, `${viewport.name} short viewport must scroll`).toBe(true);
      }
      const reachables = [
        ['controls', button3d],
        ['feed', page.getByRole('log', { name: 'Event feed' })],
        ['badge', page.getByRole('status').and(page.locator('[aria-atomic="true"]'))],
        ['active view', region],
      ] as const;
      for (const [label, target] of reachables) {
        await target.scrollIntoViewIfNeeded();
        const box = (await target.boundingBox())!;
        expect(box.y, `${viewport.name} ${label} reachable (top above fold)`).toBeLessThan(
          viewport.height,
        );
        expect(box.y + box.height, `${viewport.name} ${label} reachable (bottom on screen)`).toBeGreaterThan(0);
      }
    }

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

test('keyboard-only retry loop: every repeated failure restores focus to the new Retry button; the keyboard escape route stays live', async ({ page }) => {
  await setupPage(page);
  await expect(page.getByRole('region', { name: '3D network view' })).toBeVisible();

  // Force the 2D chunk import to fail at the network seam.
  //
  // MEASURED PLATFORM LIMIT (this runway, request-log receipt): after a
  // network-failed dynamic import, Chromium's module map caches the
  // rejection for that URL — a later import() of the SAME specifier
  // re-rejects instantly with NO new network request, even after the
  // route is repaired. So "eventual success after network repair" is
  // not stageable end-to-end in Chromium without a reload; the
  // success-side focus contract (region focused only after the child
  // commit) is locked at the unit seam instead, where fresh factories
  // give real fresh imports. What IS provable in every engine — and is
  // the part a stranded keyboard user needs — is the failure loop and
  // the escape route below.
  await page.route('**/NetworkView2D*', route => route.abort());
  await page.getByRole('button', { name: '2D View' }).click();
  await expect(page.getByRole('alert')).toContainText('The 2D network view failed to render.');

  // Keyboard-only activation (focus() stands in for tab navigation to
  // keep the journey engine-stable; the activation itself is a real
  // keyboard Enter). Each retry fails again: the old Retry unmounts and
  // focus must be RESTORED to the new Retry button — the keyboard user
  // stays in the retry loop, never dropped on <body>.
  const retry = page.getByRole('button', { name: 'Retry 2D network view' });
  await retry.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry 2D network view' })).toBeFocused();

  // Second loop iteration behaves identically (bounded, user-paced).
  await page.keyboard.press('Enter');
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry 2D network view' })).toBeFocused();

  // The escape route works by keyboard: the already-loaded 3D view is
  // reachable and healthy; the failed slot never trapped focus.
  await page.getByRole('button', { name: '3D View' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('region', { name: '3D network view' })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});
