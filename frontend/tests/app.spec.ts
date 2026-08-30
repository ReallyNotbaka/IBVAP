import { test, expect } from '@playwright/test';

test.describe('IBVAP Frontend E2E Test Suite', () => {
  test.beforeEach(async ({ page }) => {
    // Listen for uncaught runtime exceptions
    page.on('pageerror', (err) => {
      console.error('Unhandled page exception:', err.message);
    });
  });

  test('loads home page with navbar navigation', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/IBVAP/i);

    // Verify Navbar presence and key navigation links
    const nav = page.locator('nav');
    await expect(nav).toBeVisible();
    await expect(nav.getByRole('link', { name: /overview/i })).toBeVisible();
    await expect(nav.getByRole('link', { name: /monitor/i })).toBeVisible();
    await expect(nav.getByRole('link', { name: /cameras/i })).toBeVisible();
    await expect(nav.getByRole('link', { name: /alerts/i })).toBeVisible();
    await expect(nav.getByRole('link', { name: /health/i })).toBeVisible();

  });

  test('navigates to Overview page', async ({ page }) => {
    await page.goto('/overview');
    await expect(page.locator('nav')).toBeVisible();
    // Verify page rendered
    await expect(page.locator('body')).not.toBeEmpty();
  });

  test('navigates to Monitor page', async ({ page }) => {
    await page.goto('/monitor');
    await expect(page.locator('nav')).toBeVisible();
    await expect(page.locator('body')).not.toBeEmpty();
  });

  test('navigates to Connect Phone camera wizard', async ({ page }) => {
    await page.goto('/connect/phone');
    await expect(page.locator('nav')).toBeVisible();
    // Verify wizard input fields or instructions exist
    await expect(page.locator('body')).toContainText(/phone|camera|ip/i);
  });

  test('navigates to Alerts page', async ({ page }) => {
    await page.goto('/alerts');
    await expect(page.locator('nav')).toBeVisible();
    await expect(page.locator('body')).toContainText(/alert/i);
  });

  test('navigates to Health diagnostics page', async ({ page }) => {
    await page.goto('/health');
    await expect(page.locator('nav')).toBeVisible();
    await expect(page.locator('body')).toContainText(/health|status/i);
  });
});
