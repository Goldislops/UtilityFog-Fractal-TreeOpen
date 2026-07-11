import { test, expect } from '@playwright/test';

test('app loads and displays root element', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#root')).toBeVisible();
  await expect(page).toHaveTitle(/utilityfog|vite|react/i);
});

test('app renders without JavaScript errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  expect(errors).toHaveLength(0);
});

test('view switching: default 3D, accessible toggle to 2D and back', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/');

  const btn2d = page.getByRole('button', { name: '2D View' });
  const btn3d = page.getByRole('button', { name: '3D View' });
  // Semantic regions (role + accessible name), not CSS selectors. The
  // region wrappers use display:contents (no box of their own), so
  // presence is asserted with toBeAttached/toHaveCount and visibility on
  // the canvas each view renders inside its region.
  const region2d = page.getByRole('region', { name: '2D network view' });
  const region3d = page.getByRole('region', { name: '3D network view' });

  // Initial state: 3D selected and rendered, 2D absent.
  await expect(btn3d).toHaveAttribute('aria-pressed', 'true');
  await expect(btn2d).toHaveAttribute('aria-pressed', 'false');
  await expect(region3d).toBeAttached();
  await expect(region3d.locator('canvas')).toBeVisible();
  await expect(region2d).toHaveCount(0);

  // Switch to 2D: selected state and rendered region both update.
  await btn2d.click();
  await expect(btn2d).toHaveAttribute('aria-pressed', 'true');
  await expect(btn3d).toHaveAttribute('aria-pressed', 'false');
  await expect(region2d).toBeAttached();
  await expect(region2d.locator('canvas')).toBeVisible();
  await expect(region3d).toHaveCount(0);

  // Switch back to 3D: original state restored.
  await btn3d.click();
  await expect(btn3d).toHaveAttribute('aria-pressed', 'true');
  await expect(btn2d).toHaveAttribute('aria-pressed', 'false');
  await expect(region3d).toBeAttached();
  await expect(region3d.locator('canvas')).toBeVisible();
  await expect(region2d).toHaveCount(0);

  // No page-level JavaScript errors across the whole sequence.
  expect(errors).toHaveLength(0);
});
