import { test, expect, Page } from '@playwright/test';

// Package AL: forced no-WebGL journey, run in EVERY engine of the
// project matrix. The init script nulls out webgl/webgl2 context
// creation semantically (and counts probe attempts), so the same
// journey is deterministic in Chromium, Firefox and WebKit regardless
// of the machine's real GPU stack.

interface ProbeWindow extends Window {
  __webglContextRequests: number;
}

async function setupNoWebGL(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as ProbeWindow;
    w.__webglContextRequests = 0;
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      type: string,
      ...rest: unknown[]
    ) {
      if (String(type).includes('webgl')) {
        w.__webglContextRequests++;
        return null;
      }
      return (original as (this: HTMLCanvasElement, t: string, ...r: unknown[]) => unknown).call(
        this,
        type,
        ...rest,
      );
    } as typeof HTMLCanvasElement.prototype.getContext;
  });
  await page.goto('/');
  await expect(page.locator('#root')).toBeVisible();
}

const contextRequests = (page: Page) =>
  page.evaluate(() => (window as unknown as ProbeWindow).__webglContextRequests);

test('no-WebGL: shell stays alive, the 3D region carries an accessible fallback with a 44px Use 2D view button', async ({ page }) => {
  await setupNoWebGL(page);

  const region = page.getByRole('region', { name: '3D network view' });
  await expect(region).toContainText('no usable WebGL support');

  // Shell alive around the gated region: controls, badge, feed.
  await expect(page.getByRole('button', { name: '2D View', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '3D View' })).toBeVisible();
  await expect(page.getByRole('status').and(page.locator('[aria-atomic="true"]'))).toBeVisible();
  await expect(page.getByRole('log', { name: 'Event feed' })).toBeVisible();

  // The recovery control meets the 44x44 CSS-pixel floor.
  const use2d = page.getByRole('button', { name: 'Use 2D view' });
  await expect(use2d).toBeVisible();
  const box = (await use2d.boundingBox())!;
  expect(box.width).toBeGreaterThanOrEqual(44);
  expect(box.height).toBeGreaterThanOrEqual(44);
});

test('no-WebGL: probing is bounded — view switches and time never re-probe', async ({ page }) => {
  await setupNoWebGL(page);
  await expect(page.getByRole('button', { name: 'Use 2D view' })).toBeVisible();

  // The single mount-time probe issues at most two context requests
  // (webgl2 then webgl); StrictMode's dev double-effect can at most
  // double that. The load-bearing assertion is STABILITY below.
  const initial = await contextRequests(page);
  expect(initial).toBeGreaterThanOrEqual(1);
  expect(initial).toBeLessThanOrEqual(4);

  await page.getByRole('button', { name: '2D View', exact: true }).click();
  await expect(page.getByRole('region', { name: '2D network view' })).toBeVisible();
  await page.getByRole('button', { name: '3D View' }).click();
  await expect(page.getByRole('button', { name: 'Use 2D view' })).toBeVisible();
  await page.waitForTimeout(500);
  expect(await contextRequests(page), 'no re-probe on switches or over time').toBe(initial);
});

test('no-WebGL: Use 2D view switches to a working, stable 2D view with no extra churn', async ({ page }) => {
  await setupNoWebGL(page);
  await page.getByRole('button', { name: 'Use 2D view' }).click();

  const region2d = page.getByRole('region', { name: '2D network view' });
  await expect(region2d).toBeVisible();
  await expect(page.getByRole('button', { name: '2D View', exact: true })).toHaveAttribute('aria-pressed', 'true');
  // The 2D view renders on a 2d canvas context — unaffected by the gate.
  await expect(region2d.locator('canvas')).toBeVisible();

  // Stable: still standing after a settle window, shell intact.
  await page.waitForTimeout(500);
  await expect(region2d).toBeVisible();
  await expect(page.getByRole('log', { name: 'Event feed' })).toBeVisible();
  await expect(page.getByRole('status').and(page.locator('[aria-atomic="true"]'))).toBeVisible();
});
