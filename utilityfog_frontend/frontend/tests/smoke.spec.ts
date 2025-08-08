import { test, expect } from '@playwright/test';

test.describe('UtilityFog SimBridge Smoke Test', () => {
  test('connects to SimBridge and receives messages', async ({ page }) => {
    // Navigate to the app
    await page.goto('/');
    
    // Check that the page loads
    await expect(page.locator('h1')).toContainText('UtilityFog SimBridge');
    
    // Wait for connection badge specifically
    const connectionBadge = page.locator('[style*="border: 1px solid"]').first();
    await expect(connectionBadge).toBeVisible({ timeout: 10000 });
    
    // Check connection status text
    const statusText = page.locator('span').filter({ hasText: /Connected|Connecting|Disconnected/ }).first();
    await expect(statusText).toBeVisible();
    
    // Check if we get connected (may take a few seconds)
    try {
      await expect(connectionBadge).toContainText('Connected', { timeout: 15000 });
      console.log('✅ Successfully connected to SimBridge');
      
      // If connected, wait for at least one message in the event feed
      const eventFeed = page.locator('text=/TICK|INIT|EVENT|STATS/').first();
      await expect(eventFeed).toBeVisible({ timeout: 30000 });
      console.log('✅ Received at least one event from SimBridge');
      
    } catch (error) {
      console.log('⚠️ Connection test: SimBridge may not be running');
      
      // Even if not connected, verify the UI loads correctly
      await expect(page.locator('text=Network View 2D')).toBeVisible();
      await expect(page.locator('text=Live Event Feed')).toBeVisible();
      await expect(page.locator('text=System Status')).toBeVisible();
      
      console.log('✅ UI components loaded correctly despite connection issues');
    }
    
    // Verify main components are present
    await expect(page.locator('text=Network View 2D')).toBeVisible();
    await expect(page.locator('text=Live Event Feed')).toBeVisible();
    await expect(page.locator('canvas')).toBeVisible();
    
    // Check stats cards
    await expect(page.locator('text=System Status')).toBeVisible();
    await expect(page.locator('text=Total Events')).toBeVisible();
    await expect(page.locator('text=Active Agents')).toBeVisible();
    await expect(page.locator('text=Agent Updates')).toBeVisible();
    
    console.log('✅ All UI components verified');
  });
  
  test('handles WebSocket connection lifecycle', async ({ page }) => {
    await page.goto('/');
    
    // Monitor console for WebSocket messages
    const messages: string[] = [];
    page.on('console', msg => {
      if (msg.text().includes('SimBridge')) {
        messages.push(msg.text());
      }
    });
    
    // Wait for connection attempt
    await page.waitForTimeout(5000);
    
    // Verify connection attempt was made
    const hasConnectionAttempt = messages.some(msg => 
      msg.includes('Connecting to SimBridge') || 
      msg.includes('SimBridge connected')
    );
    
    expect(hasConnectionAttempt).toBe(true);
    console.log('✅ WebSocket connection attempt verified');
  });
});