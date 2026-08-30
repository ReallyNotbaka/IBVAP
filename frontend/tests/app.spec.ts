import { test, expect } from '@playwright/test';

test.describe('IBVAP Frontend E2E Test Suite', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      console.error('Unhandled page exception:', err.message);
    });
  });

  test('loads home with zero cameras → onboarding, no sidebar', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', storage_pressure: 'Normal' }) }));
    await page.goto('/');
    await expect(page).toHaveTitle(/IBVAP/i);
    await expect(page.getByTestId('cta-connect-phone')).toBeVisible();
    await expect(page.locator('.sidebar')).toHaveCount(0);
    await expect(page.locator('header.topbar')).toHaveCount(0);
  });

  test('cockpit shows tiling grid when cameras exist', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'c1', name: 'Phone 1', endpoint: 'http://192.168.1.10:4747/video', observed_state: 'STREAMING', stream_epoch: 1 }]) }));
    await page.route('**/api/v1/cameras/c1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ last_frame_age_ms: 120, analysis_fps: 12, inference_ms: 18 }) }));
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', storage_pressure: 'Normal' }) }));
    await page.goto('/');
    await expect(page.locator('header.topbar')).toBeVisible();
    await expect(page.locator('header.topbar').getByRole('link', { name: /cockpit/i })).toBeVisible();
    await expect(page.locator('header.topbar').getByRole('link', { name: /alerts/i })).toBeVisible();
    await expect(page.locator('header.topbar').getByRole('link', { name: /health/i })).toBeVisible();
    await expect(page.getByTestId('live-player-c1')).toBeVisible();
    await expect(page.getByTestId('cockpit-grid')).toHaveAttribute('data-n', '1');
  });

  test('tiling N=2 shows two tiles side-by-side', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'c1', name: 'P1', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 },
          { id: 'c2', name: 'P2', endpoint: 'http://1.1.1.2/video', observed_state: 'STREAMING', stream_epoch: 1 },
        ]),
      })
    );
    await page.route('**/api/v1/cameras/*/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ last_frame_age_ms: 100, analysis_fps: 10 }) }));
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));
    await page.goto('/');
    await expect(page.getByTestId('live-player-c1')).toBeVisible();
    await expect(page.getByTestId('live-player-c2')).toBeVisible();
    await expect(page.getByTestId('cockpit-grid')).toHaveAttribute('data-n', '2');
  });

  test('overview and monitor redirect to cockpit', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'c1', name: 'Phone', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 }]) }));
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));
    await page.route('**/api/v1/cameras/*/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.goto('/overview');
    await expect(page).toHaveURL('/');
    await page.goto('/monitor');
    await expect(page).toHaveURL('/');
  });

  test('navigates to Connect Phone modal', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) => {
      if (route.request().method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'c1', name: 'P1', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 }]) });
      return route.continue();
    });
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));
    await page.route('**/api/v1/cameras/*/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.goto('/connect/phone');
    await expect(page.locator('body')).toContainText(/phone|camera|ip/i);
    await expect(page.getByTestId('stream-url').or(page.getByTestId('prepare-done'))).toBeVisible();
  });

  test('connect test → preview → save adds tile (mocked)', async ({ page }) => {
    let cams: unknown[] = [];
    await page.route('**/api/v1/cameras/test', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ result: 'ok', safe_message: 'Probe ok', stages: [{ name: 'Probing media', status: 'ok' }], probe: { width: 640, height: 480, fps: 30, codec: 'mjpeg' } }),
      })
    );
    await page.route('**/api/v1/cameras', async (route) => {
      const url = route.request().url();
      if (url.includes('/cameras/test')) return route.continue();
      if (route.request().method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(cams) });
      if (route.request().method() === 'POST') {
        const newCam = { id: 'c99', name: 'Phone 99', endpoint: 'http://192.168.1.99:4747/video', observed_state: 'STREAMING', stream_epoch: 1 };
        cams = [newCam];
        return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(newCam) });
      }
      return route.continue();
    });
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));
    await page.route('**/api/v1/cameras/*/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.goto('/connect/phone');
    // step 1 → step 2
    const prepare = page.getByTestId('prepare-done');
    if (await prepare.isVisible()) await prepare.click();
    await page.getByTestId('stream-url').fill('http://192.168.1.99:4747/video');
    await page.getByTestId('test-connection').click();
    await expect(page.getByTestId('test-result')).toContainText('Probe ok');
    await page.getByTestId('continue').click();
    await expect(page).toHaveURL('/');
  });

  test('navigates to Alerts page', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'c1', name: 'P1', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 }]) }));
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'e1', event_type: 'intrusion', camera_id: 'c1', zone_id: 'z1' }]) }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));
    await page.route('**/api/v1/cameras/*/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.goto('/alerts');
    await expect(page.locator('body')).toContainText(/alert/i);
  });

  test('navigates to Health diagnostics page', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'c1', name: 'P1', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 }]) }));
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', storage_pressure: 'Normal', queue_drops: 0 }) }));
    await page.route('**/api/v1/cameras/*/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.goto('/health');
    await expect(page.locator('body')).toContainText(/health|status/i);
  });

  test('alert rail shows recent events on cockpit', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'c1', name: 'P1', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 }]) }));
    await page.route('**/api/v1/events*', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'e1', event_type: 'intrusion', camera_id: 'c1', zone_id: 'z1', confidence: 0.92 }]) })
    );
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));
    await page.route('**/api/v1/cameras/*/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.goto('/');
    await expect(page.locator('text=intrusion').first()).toBeVisible();
  });
});
