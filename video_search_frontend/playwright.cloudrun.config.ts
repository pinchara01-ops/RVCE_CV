import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  use: { baseURL: 'http://127.0.0.1:8080', trace: 'retain-on-failure' },
  projects: [
    { name: 'cloud-run-desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'cloud-run-mobile', use: { ...devices['Pixel 7'] } },
  ],
})
