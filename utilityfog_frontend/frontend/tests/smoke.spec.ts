import { test, expect } from '@playwright/test';

test('app loads and displays basic elements', async ({ page }) => {
  await page.goto('/');

  // Check if the page title is correct
  await expect(page).toHaveTitle(/UtilityFog 3D Visualization/);

  // Check if the main app container is present
  await expect(page.locator('.app-container')).toBeVisible();

  // Check if the controls are present
  await expect(page.getByText('2D View')).toBeVisible();
  await expect(page.getByText('3D View')).toBeVisible();

  // Check if the connection badge is present
  await expect(page.locator('.connection-badge')).toBeVisible();

  // Check if the event feed is present
  await expect(page.getByText('Event Feed')).toBeVisible();
});

test('can switch between 2D and 3D views', async ({ page }) => {
  await page.goto('/');

  // Default should be 3D view
  // Switch to 2D view
  await page.getByText('2D View').click();

  // Switch back to 3D view
  await page.getByText('3D View').click();

  // Test passes if no errors occur during view switching
});

test('connection badge shows disconnected state initially', async ({ page }) => {
  await page.goto('/');

  // Should show disconnected state since there's no real WebSocket server
  await expect(page.getByText('Disconnected')).toBeVisible();
});

test('event feed is initially empty', async ({ page }) => {
  await page.goto('/');

  // Event feed should show "No events yet..."
  await expect(page.getByText('No events yet...')).toBeVisible();
});

test('3D canvas is rendered', async ({ page }) => {
  await page.goto('/');

  // Check if the canvas element is present (from react-three-fiber)
  await expect(page.locator('canvas')).toBeVisible();
});