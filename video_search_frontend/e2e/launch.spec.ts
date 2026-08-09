import { expect, test } from '@playwright/test'

test('fresh visitor reaches launch demo without technical onboarding', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /Search any video archive/i })).toBeVisible()
  await expect(page.getByText('No account needed · 2 free live searches · 13 Indian languages')).toBeVisible()
  await expect(page.getByText(/choose a deployment profile/i)).toHaveCount(0)
  await expect(page.getByText(/paste an api key/i)).toHaveCount(0)
  await expect(page.getByRole('button', { name: /ATM surveillance/i })).toBeVisible()
  await expect(page.getByRole('button', { name: /Show the moment someone approaches the ATM/i })).toBeVisible()
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  )
  expect(hasHorizontalOverflow).toBe(false)
})

test('launch metadata and informational routes remain available', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle('Aperture: Multilingual Search for Any Moment in Your Video')
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute('content', /og-aperture\.png$/)
  await page.goto('/how-it-works')
  await expect(page.locator('h1')).toBeVisible()
  await page.goto('/design')
  await expect(page.locator('h1')).toBeVisible()
  await page.goto('/tests')
  await expect(page.getByText('Video with no audio track')).toBeVisible()
})
