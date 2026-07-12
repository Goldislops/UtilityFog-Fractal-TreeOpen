import { test, expect } from '@playwright/test';

// Package AN-1 (issue #2 acceptance audit): camera view presets — the
// unmet half of "camera controls and view presets" (OrbitControls
// interaction already ships). Semantic, engine-portable assertions only:
// the preset group is an accessible control surface inside the 3D
// region, every preset is keyboard-operable without error, and the view
// survives. Camera coordinates themselves are locked at the unit seam
// (cameraPresets tests) — E2E asserts the ACCESSIBLE CONTRACT, not
// WebGL matrix state, which headless GPU stacks render unobservable.

test('view presets: accessible group, 44px keyboard-operable actions, stable view', async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on('console', m => {
    // No fake-socket harness here, so the app's real WebSocket cannot
    // connect — WebKit (unlike Chromium) surfaces that environmental
    // failure as a console error. Application-owned diagnostics are what
    // this assertion guards.
    if (m.type() === 'error' && !m.text().includes('WebSocket connection')) {
      consoleErrors.push(m.text());
    }
  });
  await page.goto('/');
  await expect(page.locator('#root')).toBeVisible();

  const group = page.getByRole('group', { name: 'Camera view presets' });
  await expect(group).toBeVisible();

  for (const name of ['Default view', 'Top view', 'Side view']) {
    const button = group.getByRole('button', { name });
    await expect(button).toBeVisible();
    const box = (await button.boundingBox())!;
    expect(box.width, `${name} touch width`).toBeGreaterThanOrEqual(44);
    expect(box.height, `${name} touch height`).toBeGreaterThanOrEqual(44);
    // Keyboard-only activation: focus + Enter must be a safe action in
    // every engine, including before/after the canvas settles.
    await button.focus();
    await page.keyboard.press('Enter');
  }

  // The 3D view is intact after all three presets, and switching away and
  // back (which remounts the canvas) still shows the preset surface.
  await expect(page.getByRole('region', { name: '3D network view' })).toBeVisible();
  await page.getByRole('button', { name: '2D View', exact: true }).click();
  await expect(page.getByRole('region', { name: '2D network view' })).toBeVisible();
  await page.getByRole('button', { name: '3D View' }).click();
  await expect(page.getByRole('group', { name: 'Camera view presets' })).toBeVisible();

  expect(consoleErrors).toEqual([]);
});
