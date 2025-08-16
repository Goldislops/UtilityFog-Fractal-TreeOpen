import { defineConfig, devices } from '@playwright/test'

const PORT = process.env.PORT || 4173

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: [['html', { open: 'never' }]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    headless: true,
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run preview -- --port ' + PORT,
    url: `http://localhost:${PORT}/`,
    reuseExistingServer: true,
    timeout: 120_000
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } }
  ]
})