import { test, expect } from '@playwright/test';

test.describe('Operational Features & Capabilities Test Suite', () => {
  test('Alerts Console displays categorized tabs, deduplication debounce toggle, and search filter', async ({ page }) => {
    // Mock cameras
    await page.route('**/api/v1/cameras', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'cam1', name: 'North Gate', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 },
          { id: 'cam2', name: 'South Perimeter', endpoint: 'http://1.1.1.2/video', observed_state: 'STREAMING', stream_epoch: 1 },
        ]),
      })
    );

    // Mock rich events spanning watchlist matches, intrusions, exits, and system events
    await page.route('**/api/v1/events*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'ev-1',
            camera_id: 'cam1',
            zone_id: 'restricted-fence',
            track_id: 101,
            event_type: 'zone_intrusion',
            created_at: Math.floor(Date.now() / 1000) - 10,
            explanation: { threat_level: 'HIGH', rule: 'Restricted fence breach' },
          },
          {
            id: 'ev-2',
            camera_id: 'cam1',
            zone_id: 'restricted-fence',
            track_id: 101,
            event_type: 'zone_intrusion',
            created_at: Math.floor(Date.now() / 1000) - 5,
            explanation: { threat_level: 'HIGH', rule: 'Restricted fence breach' },
          },
          {
            id: 'ev-3',
            camera_id: 'cam2',
            zone_id: 'loading-bay',
            track_id: 102,
            event_type: 'zone_exit',
            created_at: Math.floor(Date.now() / 1000) - 15,
            explanation: { threat_level: 'INFO', rule: 'Target departed loading bay' },
          },
          {
            id: 'ev-4',
            camera_id: 'cam1',
            event_type: 'watchlist_match',
            created_at: Math.floor(Date.now() / 1000) - 20,
            explanation: { suspect_name: 'Vikram Singh', threat_level: 'CRITICAL', tier: 'RED' },
          },
          {
            id: 'ev-5',
            camera_id: 'cam2',
            event_type: 'system_low_vis',
            created_at: Math.floor(Date.now() / 1000) - 30,
            explanation: { rule: 'Sudden IR illumination drop detected' },
          },
        ]),
      })
    );

    await page.route('**/api/v1/health', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) })
    );

    await page.goto('/alerts');

    // 1. Verify title & header
    await expect(page.getByRole('heading', { name: /Operational Alerts Console/i })).toBeVisible();

    // 2. Verify all 5 categorized tabs exist
    const tabAll = page.getByRole('button', { name: /^All/i });
    const tabWatchlist = page.getByRole('button', { name: /Watchlist Matches/i });
    const tabIntrusions = page.getByRole('button', { name: /Intrusions/i });
    const tabExits = page.getByRole('button', { name: /Exits/i });
    const tabSystem = page.getByRole('button', { name: /System/i });

    await expect(tabAll).toBeVisible();
    await expect(tabWatchlist).toBeVisible();
    await expect(tabIntrusions).toBeVisible();
    await expect(tabExits).toBeVisible();
    await expect(tabSystem).toBeVisible();

    // 3. Verify deduplication collapsed the 2 rapid intrusions into 1 grouped entry with a counter
    await expect(page.getByText(/×2 occurrences/i)).toBeVisible();

    // 4. Test filtering by tab
    await tabIntrusions.click();
    await expect(page.getByText(/Restricted fence breach/i)).toBeVisible();
    await expect(page.getByText(/Vikram Singh/i)).not.toBeVisible();

    await tabWatchlist.click();
    await expect(page.getByText(/Vikram Singh/i)).toBeVisible();
    await expect(page.getByText(/Restricted fence breach/i)).not.toBeVisible();

    await tabExits.click();
    await expect(page.getByText(/Target departed loading bay/i)).toBeVisible();

    // 5. Test search filter
    await tabAll.click();
    const searchInput = page.getByPlaceholder(/Search alerts/i);
    await searchInput.fill('Vikram');
    await expect(page.getByText(/Vikram Singh/i)).toBeVisible();
    await expect(page.getByText(/loading bay/i)).not.toBeVisible();
  });

  test('Health Dashboard displays DirectML accelerator telemetry, memory metrics, and camera status', async ({ page }) => {
    // Mock health with hardware telemetry
    await page.route('**/api/v1/health', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          version: '0.1.0',
          timestamp: new Date().toISOString(),
          checks: {
            mediamtx: 'ok',
            onnxruntime: 'ok (DmlExecutionProvider)',
            sqlite: 'ok',
          },
          system: {
            gpu_accelerator: 'DirectML (DmlExecutionProvider)',
            directml_available: true,
            cuda_available: false,
            active_providers: ['DmlExecutionProvider', 'CPUExecutionProvider'],
            memory_total_mb: 16384,
            memory_avail_mb: 8192,
            memory_used_mb: 8192,
            memory_percent: 50.0,
            active_model: 'yolo26n',
            active_runtime: 'DirectML',
            process_uptime_seconds: 450,
          },
        }),
      })
    );

    // Mock cameras
    await page.route('**/api/v1/cameras', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'c1', name: 'Gate Alpha', endpoint: 'rtsp://10.0.0.1/live', observed_state: 'STREAMING', stream_epoch: 1 },
        ]),
      })
    );

    // Mock per-camera health
    await page.route('**/api/v1/cameras/c1/health', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          camera_id: 'c1',
          observed_state: 'STREAMING',
          source_fps: 30.0,
          analysis_fps: 29.8,
          inference_ms: 7.2,
          last_frame_age_ms: 32,
          queue_drops: 0,
          decode_errors: 0,
          reconnect_count: 0,
        }),
      })
    );

    await page.route('**/api/v1/capabilities', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ directml: true }),
      })
    );

    await page.goto('/health');

    // 1. Verify health title
    await expect(page.getByRole('heading', { name: /System & Pipeline Diagnostics/i })).toBeVisible();

    // 2. Verify DirectML accelerator telemetry card
    await expect(page.getByText(/DirectML \(DmlExecutionProvider\)/i)).toBeVisible();

    // 3. Verify Memory metrics
    await expect(page.getByText(/System RAM Load/i)).toBeVisible();
    await expect(page.getByText(/8192 MB/i)).toBeVisible();

    // 4. Verify camera health telemetry row
    await expect(page.getByText('Gate Alpha')).toBeVisible();
    await expect(page.getByText('30.0 FPS')).toBeVisible();
    await expect(page.getByText('7.2 ms')).toBeVisible();
    await expect(page.getByRole('button', { name: /Reconnect/i })).toBeVisible();
  });

  test('Model Selector allows deleting downloaded weights and imports via USB drag-drop', async ({ page }) => {
    let deleteCalled = false;

    // Mock models with yolo26n active, yolo26s installed, yolo26m uninstalled
    await page.route('**/api/v1/models', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          models: [
            {
              name: 'yolo26n',
              filename: 'yolo26n.onnx',
              description: 'Nano baseline model',
              size_mb: 6.2,
              is_installed: true,
              is_active: true,
              est_latency_ms: 5.2,
              mAP_val: 39.8,
            },
            {
              name: 'yolo26s',
              filename: 'yolo26s.onnx',
              description: 'Small enhanced model',
              size_mb: 22.4,
              is_installed: true,
              is_active: false,
              est_latency_ms: 8.5,
              mAP_val: 47.1,
            },
            {
              name: 'yolo26m',
              filename: 'yolo26m.onnx',
              description: 'Medium balanced model',
              size_mb: 51.0,
              is_installed: false,
              is_active: false,
              est_latency_ms: 14.0,
              mAP_val: 51.5,
            },
          ],
          active_model: 'yolo26n',
        }),
      })
    );

    await page.route('**/api/v1/models/yolo26s/weights', (route) => {
      deleteCalled = true;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'deleted', model_name: 'yolo26s', filename: 'yolo26s.onnx' }),
      });
    });

    await page.route('**/api/v1/cameras', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{ id: 'c1', name: 'Camera 1', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 }]),
      })
    );
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));

    await page.goto('/');

    // Open Models Modal from Topbar
    const modelBadge = page.locator('header.topbar button').filter({ hasText: /YOLO26|ENGINE|MODEL/i }).first();
    await modelBadge.click();

    // 1. Verify modal opened
    await expect(page.getByRole('heading', { name: /Dynamic YOLO26 Neural Model Switcher/i })).toBeVisible();

    // 2. Base model yolo26n is active and has NO Delete button
    await expect(page.getByTestId('delete-weights-yolo26n')).toHaveCount(0);

    // 3. Installed model yolo26s HAS Delete Weights button
    const deleteBtn = page.getByTestId('delete-weights-yolo26s');
    await expect(deleteBtn).toBeVisible();

    // Handle dialog confirmation
    page.on('dialog', (dialog) => dialog.accept());
    await deleteBtn.click();
    expect(deleteCalled).toBe(true);

    // 4. Switch to Air-Gapped / USB Import tab
    const usbTab = page.getByRole('button', { name: /Air-Gapped \/ USB Weight Import/i });
    await usbTab.click();

    // Verify USB Drag & Drop zone is visible
    await expect(page.getByText(/Click to select or drag & drop USB \.onnx weights here/i)).toBeVisible();
    await expect(page.getByText(/Supported architectures: YOLO26s, YOLO26m, YOLO26l, YOLO26x/i)).toBeVisible();
  });
});
