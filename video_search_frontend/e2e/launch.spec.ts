import { expect, test } from '@playwright/test'

test('fresh visitor reaches launch demo without technical onboarding', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /Search any video archive/i })).toBeVisible()
  await expect(page.getByText('No account needed · 2 free live searches · 13 Indian languages')).toBeVisible()
  await expect(page.getByText(/choose a deployment profile/i)).toHaveCount(0)
  await expect(page.getByText(/paste an api key/i)).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Animals enjoying belly rubs/i })).toBeVisible()
  await expect(page.getByRole('textbox', { name: /Describe the moment/i })).toHaveCount(0)
  await expect(page.getByText(/Exact matching moments/i)).toHaveCount(0)
  await page.getByRole('button', { name: /Animals enjoying belly rubs/i }).click()
  await expect(page.getByText(/Selected:/i)).toBeVisible()
  await expect(page.getByRole('button', { name: /Find the moment a dog gets a belly rub/i })).toBeVisible()
  await expect(page.getByRole('button', { name: /Upload yours/i })).toBeVisible()
  await page.getByRole('button', { name: /Upload yours/i }).click()
  await page.getByLabel(/^Choose one video file/i).setInputFiles({
    name: 'personal-video.webm',
    mimeType: 'video/webm',
    buffer: Buffer.from([0x1a, 0x45, 0xdf, 0xa3, 0x00]),
  })
  await expect(page.getByText('Selected: personal-video.webm', { exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: /Describe the moment/i })).toBeEnabled()
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  )
  expect(hasHorizontalOverflow).toBe(false)
})

test('launch metadata and informational routes remain available', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle('Aperture: Multilingual Search for Any Moment in Your Video')
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute('content', /og-aperture\.png$/)
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', /favicon\.svg/)
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute('href', '/site.webmanifest')
  await page.goto('/how-it-works')
  await expect(page.locator('h1')).toBeVisible()
  await page.goto('/design')
  await expect(page.locator('h1')).toBeVisible()
})

test('removed tests route leaves no tests page in the public frontend', async ({ page }) => {
  await page.goto('/tests')
  await expect(page.getByRole('heading', { name: /Search any video archive/i })).toBeVisible()
  await expect(page.getByRole('link', { name: /^Tests$/i })).toHaveCount(0)
  await expect(page.getByText('Video with no audio track')).toHaveCount(0)
})
