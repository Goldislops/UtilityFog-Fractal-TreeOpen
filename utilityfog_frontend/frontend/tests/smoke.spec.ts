import { test, expect } from '@playwright/test'

test('home renders', async ({ page, baseURL }) => {
  await page.goto(baseURL ?? '/')
  // Expect app root to exist
  await expect(page.locator('#root')).toBeVisible()
  // Be generous about title (Vite/React/UtilityFog)
  await expect(page).toHaveTitle(/utilityfog|vite|react/i)
})