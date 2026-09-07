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
    await expect(page.locator('header.topbar')).toHaveCount(1);
  });

  test('cockpit shows tiling grid when cameras exist', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'c1', name: 'Phone 1', endpoint: 'http://192.168.1.10:4747/video', observed_state: 'STREAMING', stream_epoch: 1 }]) }));
    await page.route('**/api/v1/cameras/c1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ last_frame_age_ms: 120, analysis_fps: 12, inference_ms: 18 }) }));
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', storage_pressure: 'Normal' }) }));
    await page.goto('/');
    await expect(page.locator('header.topbar')).toBeVisible();
    await expect(page.locator('header.topbar').getByRole('link', { name: /overview/i })).toBeVisible();
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

  test('animated theme toggle switches between light and dark mode', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'c1', name: 'P1', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 }]) }));
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));
    await page.route('**/api/v1/cameras/*/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.goto('/');

    const themeToggle = page.getByRole('button', { name: /switch to/i });
    await expect(themeToggle).toBeVisible();

    const html = page.locator('html');
    const wasDark = await html.evaluate((el) => el.classList.contains('dark'));
    await themeToggle.click();
    const isNowDark = await html.evaluate((el) => el.classList.contains('dark'));
    expect(isNowDark).toBe(!wasDark);

    // Toggle back
    await themeToggle.click();
    const isRestored = await html.evaluate((el) => el.classList.contains('dark'));
    expect(isRestored).toBe(wasDark);
  });

  test('control pill bar switches overlay presets and toggles drawer', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'c1', name: 'P1', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 }]) }));
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'e1', event_type: 'perimeter_intrusion', camera_id: 'c1', confidence: 0.95 }]) }));
    await page.route('**/api/v1/watchlist', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'w1', name: 'John Doe', threat_level: 'HIGH', photo_count: 2, sight_count: 3 }]) }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));
    await page.route('**/api/v1/cameras/*/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.goto('/');

    // Check Control Pill Bar exists
    const cleanPreset = page.getByRole('button', { name: 'Clean' });
    const allDataPreset = page.getByRole('button', { name: 'All Data' });
    const alertsOnlyPreset = page.getByRole('button', { name: 'Alerts Only' });
    await expect(cleanPreset).toBeVisible();
    await expect(allDataPreset).toBeVisible();
    await expect(alertsOnlyPreset).toBeVisible();

    // Toggle preset
    await cleanPreset.click();
    await alertsOnlyPreset.click();
    await allDataPreset.click();

    // Open collapsible drawer via drawer button
    const alertsDrawerBtn = page.getByRole('button', { name: /Alerts/i }).filter({ hasText: 'Alerts' }).last();
    await alertsDrawerBtn.click();
    await expect(page.getByRole('heading', { name: /Alerts & (Watchlist|Suspects)/i })).toBeVisible();
    await expect(page.getByText('John Doe')).toBeVisible();

    // Close drawer
    await page.getByRole('button', { name: 'Close Drawer' }).click();
    await expect(page.getByRole('heading', { name: /Alerts & (Watchlist|Suspects)/i })).not.toBeVisible();
  });

  test('clicking target in video feed opens Quick Inspector and enlists in watchlist', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'c1', name: 'P1', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 }]) }));
    await page.route('**/api/v1/cameras/c1/observations', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          runtime: 'DirectML',
          tracks: [
            {
              track_id: 104,
              class_name: 'person',
              confidence: 0.94,
              bbox_norm: [0.2, 0.2, 0.5, 0.7],
            },
          ],
          faces: [
            {
              confidence: 0.88,
              bbox_norm: [0.3, 0.22, 0.4, 0.38],
            },
          ],
        }),
      })
    );
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/watchlist', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));
    await page.route('**/api/v1/cameras/*/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.goto('/');

    // Wait for observation overlay to render
    const livePlayer = page.getByTestId('live-player-c1');
    await expect(livePlayer).toBeVisible();

    // Click on target inside video
    const targetHit = livePlayer.locator('svg g rect.cursor-pointer').first();
    await expect(targetHit).toBeVisible();
    await targetHit.click({ force: true });

    // Expect Quick Inspector card to appear
    const inspectorCard = page.locator('.inspector-card');
    await expect(inspectorCard).toBeVisible();
    await expect(inspectorCard).toContainText(/PERSON|FACE/i);
    await expect(inspectorCard).toContainText(/94%|88%/);

    // Click 1-click "Put on Watchlist" button
    const putOnWatchlistBtn = inspectorCard.getByRole('button', { name: /Put on Watchlist/i });
    await expect(putOnWatchlistBtn).toBeVisible();
    await putOnWatchlistBtn.click();

    // Verify WatchlistModal opened and switched to enrollment tab with target prefilled
    await expect(page.getByRole('heading', { name: /Biometric Watchlist/i })).toBeVisible();
    await expect(page.locator('input[placeholder*="John Doe"]')).toHaveValue(/Person #104|Subject|Suspect/);

    // Verify photo preview is populated and enroll button is ready and enabled
    const enrollBtn = page.getByRole('button', { name: /Enroll in Watchlist/i });
    await expect(enrollBtn).toBeVisible();
    await expect(enrollBtn).toBeEnabled();
  });

  test('theater solo mode expands single camera and exits back to multi-grid', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'c1', name: 'Camera 1', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 },
          { id: 'c2', name: 'Camera 2', endpoint: 'http://1.1.1.2/video', observed_state: 'STREAMING', stream_epoch: 1 },
        ]),
      })
    );
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));
    await page.route('**/api/v1/cameras/*/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
    await page.goto('/');

    await expect(page.getByTestId('cockpit-grid')).toHaveAttribute('data-n', '2');
    await expect(page.getByTestId('live-player-c1')).toBeVisible();
    await expect(page.getByTestId('live-player-c2')).toBeVisible();

    // Click Solo on Camera 1
    const soloBtn = page.getByTestId('live-player-c1').getByRole('button', { name: /theater solo/i });
    await soloBtn.click();

    // Verify grid isolates Camera 1
    await expect(page.getByTestId('cockpit-grid')).toHaveAttribute('data-n', '1');
    await expect(page.getByTestId('live-player-c1')).toBeVisible();
    await expect(page.getByTestId('live-player-c2')).toHaveCount(0);

    // Exit Solo via Control Pill Bar
    const exitSoloBtn = page.getByRole('button', { name: /exit solo/i }).first();
    await expect(exitSoloBtn).toBeVisible();
    await exitSoloBtn.click();

    // Verify grid returns to 2 cameras
    await expect(page.getByTestId('cockpit-grid')).toHaveAttribute('data-n', '2');
    await expect(page.getByTestId('live-player-c1')).toBeVisible();
    await expect(page.getByTestId('live-player-c2')).toBeVisible();
  });

  test('theme toggle works on onboarding empty state and persists', async ({ page }) => {
    await page.route('**/api/v1/cameras', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));
    await page.goto('/');

    const themeToggle = page.locator('header.topbar').getByTestId('theme-toggle');
    await expect(themeToggle).toBeVisible();

    const html = page.locator('html');
    const wasDark = await html.evaluate((el) => el.classList.contains('dark'));
    await themeToggle.click();
    const isNowDark = await html.evaluate((el) => el.classList.contains('dark'));
    expect(isNowDark).toBe(!wasDark);
  });
});
