import { test, expect } from '@playwright/test';

test.describe('Critical Target Tracking & Identification Suite', () => {
  test('renders critical target with high-visibility red box and target name across all overlay presets', async ({ page }) => {
    page.on('pageerror', (err) => console.error('PAGE ERROR:', err.message));
    page.on('console', (msg) => console.log('BROWSER CONSOLE:', msg.type(), msg.text()));

    await page.route('**/api/v1/models', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ active_model: 'yolo26n', models: [] }),
      })
    );

    await page.route('**/api/v1/cameras/*/stream*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'image/jpeg',
        body: Buffer.from(''),
      })
    );

    // 1. Mock camera, observations with a critical target, and watchlist
    await page.route('**/api/v1/cameras', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'c1',
            name: 'North Perimeter Gate',
            endpoint: 'http://192.168.1.100:8080/video',
            observed_state: 'STREAMING',
            stream_epoch: 1,
          },
        ]),
      })
    );

    // Mock observations: 1 critical target (Vikram Singh) and 1 ordinary civilian pedestrian
    await page.route('**/api/v1/cameras/*/observations', (route) => {
      console.log('OBSERVATIONS ROUTE HIT:', route.request().url());
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          runtime: 'DirectML',
          active_model: 'yolo26n',
          tracks: [
            {
              track_id: 101,
              class_name: 'person',
              confidence: 0.94,
              bbox_norm: [0.25, 0.20, 0.50, 0.75],
              identity: {
                entry_id: 'target-crit-001',
                name: 'Vikram Singh',
                threat_level: 'CRITICAL',
                score: 0.89,
                tier: 'RED',
                locked: true,
              },
              identity_locked: true,
            },
            {
              track_id: 202,
              class_name: 'person',
              confidence: 0.85,
              bbox_norm: [0.65, 0.30, 0.85, 0.80],
            },
          ],
          faces: [
            {
              confidence: 0.92,
              bbox_norm: [0.32, 0.22, 0.43, 0.36],
            },
          ],
        }),
      });
    });

    await page.route('**/api/v1/events*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'ev-crit-1',
            camera_id: 'c1',
            event_type: 'watchlist_suspect_identified',
            confidence: 0.89,
            explanation: {
              rule: 'watchlist_biometric_match',
              suspect_id: 'target-crit-001',
              suspect_name: 'Vikram Singh',
              threat_level: 'CRITICAL',
              score: 0.89,
              tier: 'RED',
            },
          },
        ]),
      })
    );

    await page.route('**/api/v1/watchlist', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'target-crit-001',
            name: 'Vikram Singh',
            threat_level: 'CRITICAL',
            notes: 'High priority watchlist target',
            photo_count: 3,
            sight_count: 5,
          },
        ]),
      })
    );

    await page.route('**/api/v1/health', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', storage_pressure: 'Normal', queue_drops: 0 }),
      })
    );

    await page.route('**/api/v1/cameras/*/health', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ last_frame_age_ms: 50, analysis_fps: 15, inference_ms: 12 }),
      })
    );

    await page.goto('/');

    const livePlayer = page.getByTestId('live-player-c1');
    await expect(livePlayer).toBeVisible();

    // ------------------------------------------------------------------------
    // Check 1: Unmistakable Red Box and Name in default preset ('all')
    // ------------------------------------------------------------------------
    // Red bounding box outline exists with stroke="#ef4444"
    const redBox = livePlayer.locator('[data-testid="critical-target-box"]');
    await expect(redBox).toBeVisible();
    await expect(redBox).toHaveAttribute('stroke', '#ef4444');

    // Reinforced corner brackets exist with stroke="#ef4444"
    const redCorner = livePlayer.locator('svg path[stroke="#ef4444"]').first();
    await expect(redCorner).toBeVisible();

    // Target's name is prominently displayed
    const nameText = livePlayer.locator('[data-testid="target-name-text"]');
    await expect(nameText).toBeVisible();
    await expect(nameText).toContainText(/VIKRAM SINGH/i);

    // Verify non-alert track (Person #202) is also visible in 'all' preset
    await expect(livePlayer.getByText('#202')).toBeVisible();

    // ------------------------------------------------------------------------
    // Check 2: Preset 'Clean' - Critical target red box and name MUST remain visible
    // ------------------------------------------------------------------------
    const cleanPresetBtn = page.getByRole('button', { name: 'Clean' });
    await cleanPresetBtn.click();

    // Critical target red box remains visible
    await expect(redBox).toBeVisible();
    // Critical target name badge remains visible
    await expect(nameText).toBeVisible();
    await expect(nameText).toContainText(/VIKRAM SINGH/i);

    // ------------------------------------------------------------------------
    // Check 3: Preset 'Alerts Only' - Critical target visible, civilian hidden
    // ------------------------------------------------------------------------
    const alertsOnlyPresetBtn = page.getByRole('button', { name: 'Alerts Only' });
    await alertsOnlyPresetBtn.click();

    // Critical target red box and name remain visible
    await expect(redBox).toBeVisible();
    await expect(nameText).toBeVisible();
    await expect(nameText).toContainText(/VIKRAM SINGH/i);

    // Civilian pedestrian (track #202) is filtered out in alerts only preset!
    await expect(livePlayer.getByText('#202')).toHaveCount(0);

    // Switch back to 'All Data'
    const allDataPresetBtn = page.getByRole('button', { name: 'All Data' });
    await allDataPresetBtn.click();
    await expect(redBox).toBeVisible();
    await expect(nameText).toBeVisible();

    // ------------------------------------------------------------------------
    // Check 4: Quick Inspector interaction with Critical Target
    // ------------------------------------------------------------------------
    // Click on critical target inside video overlay
    const targetHit = livePlayer.locator('svg g[filter*="critical-target-glow"] rect.cursor-pointer').first();
    await targetHit.click({ force: true });

    // Inspector card opens with critical target details
    const inspectorCard = page.locator('.inspector-card');
    await expect(inspectorCard).toBeVisible();
    await expect(inspectorCard).toContainText(/VIKRAM SINGH/i);
    await expect(inspectorCard).toContainText('#101');
    await expect(inspectorCard).toContainText('89%');
    await expect(inspectorCard).toContainText(/Critical Target Match/i);

    // Close inspector
    await inspectorCard.getByRole('button', { name: '✕' }).click();
    await expect(inspectorCard).not.toBeVisible();
  });

  test('critical target is never suppressed by overlapping higher-confidence civilian detection and low-confidence identified track is retained', async ({ page }) => {
    page.on('pageerror', (err) => console.error('TEST2 PAGE ERROR:', err.message));
    page.on('console', (msg) => console.log('TEST2 BROWSER CONSOLE:', msg.type(), msg.text()));

    await page.route('**/api/v1/models', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ active_model: 'yolo26n', models: [] }),
      })
    );

    await page.route('**/api/v1/cameras/*/stream*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'image/jpeg',
        body: Buffer.from(''),
      })
    );

    await page.route('**/api/v1/cameras', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'c1',
            name: 'Terminal Entry',
            endpoint: 'http://192.168.1.100:8080/video',
            observed_state: 'STREAMING',
            stream_epoch: 1,
          },
        ]),
      })
    );

    // Track 1: Civilian detection with high confidence (0.96)
    // Track 2: Critical target with lower confidence (0.42) overlapping heavily
    await page.route('**/api/v1/cameras/*/observations', (route) => {
      console.log('TEST2 OBSERVATIONS ROUTE HIT:', route.request().url());
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          runtime: 'DirectML',
          active_model: 'yolo26n',
          tracks: [
            {
              track_id: 301,
              class_name: 'person',
              confidence: 0.96,
              bbox_norm: [0.30, 0.20, 0.55, 0.75],
            },
            {
              track_id: 302,
              class_name: 'person',
              confidence: 0.42,
              bbox_norm: [0.30, 0.20, 0.55, 0.75],
              identity: {
                entry_id: 'crit-agent-zero',
                name: 'Agent Zero',
                threat_level: 'CRITICAL',
                score: 0.88,
                tier: 'RED',
                locked: true,
              },
              identity_locked: true,
            },
          ],
          faces: [],
        }),
      });
    });

    await page.route('**/api/v1/events*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    );

    await page.route('**/api/v1/watchlist', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    );

    await page.route('**/api/v1/health', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', storage_pressure: 'Normal', queue_drops: 0 }),
      })
    );

    await page.route('**/api/v1/cameras/*/health', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ last_frame_age_ms: 50, analysis_fps: 15, inference_ms: 12 }),
      })
    );

    await page.goto('/');

    const livePlayer = page.getByTestId('live-player-c1');
    await expect(livePlayer).toBeVisible();

    // Critical target red box must be rendered!
    const redBox = livePlayer.locator('[data-testid="critical-target-box"]');
    await expect(redBox).toBeVisible();
    await expect(redBox).toHaveAttribute('stroke', '#ef4444');

    // Target's name must be rendered and not overwritten by civilian
    const nameText = livePlayer.locator('[data-testid="target-name-text"]');
    await expect(nameText).toBeVisible();
    await expect(nameText).toContainText(/AGENT ZERO/i);
  });
});

