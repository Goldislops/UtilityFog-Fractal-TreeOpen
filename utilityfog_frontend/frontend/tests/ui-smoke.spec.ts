import { test, expect } from '@playwright/test';

// Make frontend resilient if backend/WebSocket is absent
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const NoopWS = class {
      constructor() {}
      close() {}
      send() {}
      addEventListener() {}
      removeEventListener() {}
    };
    // @ts-ignore
    window.WebSocket = NoopWS;
  });
});

test('app renders main shell', async ({ page }) => {
  await page.goto('/');
  // Adjust selectors to what actually renders before data arrives:
  await expect(page.getByText(/UtilityFog|Surprise|Refine/i)).toBeVisible();
});

test('badges render without data', async ({ page }) => {
  await page.goto('/');
  // Look for badge texts/components that are present even if backend is down
  await expect(page.getByText(/Surprise|Refine/i)).toBeVisible();
});
