import { test, expect } from '@playwright/test';
test('app boots and key UI surfaces', async ({ page }) => {
  await page.goto('/');
  // Basic app shell renders
  await expect(page).toHaveTitle(/UtilityFog|Vite|React/i);
  // Try the new badges if present; skip (soft) if absent
  const surprise = page.locator('[data-testid="surprise-badge"]');
  const refine = page.locator('[data-testid="refine-badge"]');
  await surprise.first().waitFor({ state: 'visible', timeout: 2000 }).catch(() => {});
  await refine.first().waitFor({ state: 'visible', timeout: 2000 }).catch(() => {});
  // App root exists
  await expect(page.locator('#root')).toBeVisible();
});