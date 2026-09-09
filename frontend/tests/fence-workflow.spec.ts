import { test, expect } from '@playwright/test';

// Minimal valid 1x1 base64 JPEG
const JPEG_1X1 = Buffer.from(
  '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=',
  'base64'
);

test.describe('Perimeter Fence & Virtual Tripwire Workflow Test Suite', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      console.error('Unhandled page exception:', err.message);
    });
    page.on('console', (msg) => {
      console.log('PAGE LOG:', msg.text());
    });
  });

  test('full fence lifecycle: 1-pt feedback, debounce, 2-pt tripwire, undo/clear, >4 pts, save & delete', async ({ page }) => {
    let savedFencePayload: any = null;
    let deleteFenceCalled = false;
    let currentCameraFence: any = null;

    await page.route(/\/api\/v1\/cameras\/.*\/stream/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'image/jpeg',
        body: JPEG_1X1,
      })
    );
    await page.route('**/api/v1/watchlist', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    );
    await page.route('**/api/v1/models', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ models: [], active_model: '' }) })
    );

    // Mock cameras
    await page.route('**/api/v1/cameras', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              id: 'cam1',
              name: 'Perimeter Sensor 01',
              endpoint: 'http://1.1.1.1/video',
              observed_state: 'STREAMING',
              stream_epoch: 1,
              fence: currentCameraFence,
            },
          ]),
        });
      }
      return route.continue();
    });

    // Mock fence PUT and DELETE endpoint
    await page.route('**/api/v1/cameras/cam1/fence', (route) => {
      if (route.request().method() === 'PUT') {
        savedFencePayload = JSON.parse(route.request().postData() || '{}');
        currentCameraFence = {
          polygon: savedFencePayload.polygon,
          fence_type: savedFencePayload.fence_type || (savedFencePayload.polygon?.length === 2 ? 'line' : 'polygon'),
          enabled: true,
          name: savedFencePayload.fence_type === 'line' ? 'User line tripwire' : 'User fence',
        };
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'ok',
            camera_id: 'cam1',
            fence: currentCameraFence,
          }),
        });
      }
      if (route.request().method() === 'DELETE') {
        deleteFenceCalled = true;
        currentCameraFence = null;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'ok',
            camera_id: 'cam1',
            fence: null,
          }),
        });
      }
      return route.continue();
    });

    // Mock events and health
    await page.route('**/api/v1/events*', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    );
    await page.route('**/api/v1/health', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) })
    );
    await page.route('**/api/v1/cameras/*/health', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
    );
    await page.route('**/api/v1/cameras/cam1/observations', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          runtime: 'DirectML',
          frame_width: 1280,
          frame_height: 720,
          tracks: [],
          faces: [],
        }),
      })
    );

    await page.goto('/');

    const livePlayer = page.getByTestId('live-player-cam1');
    await expect(livePlayer).toBeVisible();

    // 1. Initial State: "Draw fence" button is present in control pill bar
    const drawFenceBtn = page.getByRole('button', { name: /Draw fence/i });
    await expect(drawFenceBtn).toBeVisible();
    await drawFenceBtn.click();

    // Verify drawing banner and prompt
    await expect(page.getByText(/Click video to place Point 1/i)).toBeVisible();
    await expect(page.getByText(/0 pts/i)).toBeVisible();

    const videoSurface = livePlayer.locator('.cursor-crosshair');
    await expect(videoSurface).toBeVisible();

    const clickAtNorm = async (nx: number, ny: number) => {
      const box = await videoSurface.boundingBox();
      expect(box).not.toBeNull();
      await videoSurface.click({
        position: {
          x: Math.round(box!.width * nx),
          y: Math.round(box!.height * ny),
        },
      });
    };

    // 2. Click first point
    await clickAtNorm(0.2, 0.3);
    await expect(page.getByText(/1 pts/i)).toBeVisible();
    await expect(page.getByText(/Point 1 set • Click Point 2 for Line Tripwire/i)).toBeVisible();

    // Verify handle for point 1 is visible immediately in SVG
    const handle1 = livePlayer.locator('svg text').filter({ hasText: /^1$/ });
    await expect(handle1).toBeVisible();

    // 3. Double-click prevention: rapid second click in almost identical coordinates
    await clickAtNorm(0.201, 0.301);
    // Point count should STILL be 1 due to debounce (< 250ms & dist < 0.015)
    await expect(page.getByText(/1 pts/i)).toBeVisible();

    // Wait 350ms for debounce window to pass
    await page.waitForTimeout(350);

    // 4. Click second point -> 2-point Virtual Tripwire Line
    await clickAtNorm(0.8, 0.3);
    await expect(page.getByText(/2 pts \(Line Tripwire\)/i)).toBeVisible();
    await expect(page.getByText(/TRIPWIRE LINE/i)).toBeVisible();
    const saveLineBtn = page.getByRole('button', { name: /Save line fence/i });
    await expect(saveLineBtn).toBeVisible();

    // 5. Save the 2-point line fence
    await saveLineBtn.click();
    expect(savedFencePayload).not.toBeNull();
    expect(savedFencePayload.fence_type).toBe('line');
    expect(savedFencePayload.polygon).toHaveLength(2);

    // After save, verify drawing mode exits and "Redraw fence" & "Delete fence" appear
    await expect(page.getByRole('button', { name: /Redraw fence/i })).toBeVisible();
    const deleteFenceBtn = page.getByRole('button', { name: /Delete fence/i });
    await expect(deleteFenceBtn).toBeVisible();

    // 6. Test Undo and Clear functionality
    await page.getByRole('button', { name: /Redraw fence/i }).click();
    await expect(page.getByText(/0 pts/i)).toBeVisible();

    // Place 3 points
    await clickAtNorm(0.2, 0.25);
    await page.waitForTimeout(350);
    await clickAtNorm(0.7, 0.25);
    await page.waitForTimeout(350);
    await clickAtNorm(0.5, 0.55);
    await expect(page.getByText(/3 pts \(Polygon Zone\)/i)).toBeVisible();

    // Click Undo point -> drops to 2 points
    const undoBtn = page.getByRole('button', { name: /Undo point/i });
    await expect(undoBtn).toBeEnabled();
    await undoBtn.click();
    await expect(page.getByText(/2 pts \(Line Tripwire\)/i)).toBeVisible();

    // Test Backspace keyboard shortcut -> drops to 1 point
    await page.keyboard.press('Backspace');
    await expect(page.getByText(/1 pts/i)).toBeVisible();

    // Click Clear points -> drops to 0 points and disables Undo/Clear
    const clearBtn = page.getByRole('button', { name: /Clear points/i });
    await expect(clearBtn).toBeEnabled();
    await clearBtn.click();
    await expect(page.getByText(/0 pts/i)).toBeVisible();
    await expect(undoBtn).toBeDisabled();
    await expect(clearBtn).toBeDisabled();
    await page.waitForTimeout(400);

    // 7. Place > 4 points (5 points for arbitrary polygon support)
    await clickAtNorm(0.2, 0.25); // Pt 1
    await page.waitForTimeout(350);
    await clickAtNorm(0.5, 0.15); // Pt 2
    await page.waitForTimeout(350);
    await clickAtNorm(0.8, 0.25); // Pt 3
    await page.waitForTimeout(350);
    await clickAtNorm(0.7, 0.55); // Pt 4
    await page.waitForTimeout(350);
    await clickAtNorm(0.3, 0.55); // Pt 5
    await expect(page.getByText(/5 pts \(Polygon Zone\)/i)).toBeVisible();

    // Verify 5 vertex handles are rendered
    await expect(livePlayer.locator('svg text').filter({ hasText: /^1$/ })).toBeVisible();
    await expect(livePlayer.locator('svg text').filter({ hasText: /^5$/ })).toBeVisible();

    // Test removing a specific point by clicking its vertex handle circle
    const handle3 = livePlayer.locator('g').filter({ has: livePlayer.locator('svg text').filter({ hasText: /^3$/ }) }).locator('circle').first();
    if (await handle3.isVisible()) {
      await page.waitForTimeout(400);
      await handle3.click();
      await expect(page.getByText(/4 pts \(Polygon Zone\)/i)).toBeVisible();
    }

    // Save polygon fence
    const savePolygonBtn = page.getByRole('button', { name: /Save polygon fence/i });
    await expect(savePolygonBtn).toBeVisible();
    await savePolygonBtn.click();

    expect(savedFencePayload.fence_type).toBe('polygon');

    // 8. Delete fence
    await expect(deleteFenceBtn).toBeVisible();
    await deleteFenceBtn.click();
    expect(deleteFenceCalled).toBe(true);
  });

  test('ROI Intruder displays purple outline (#a855f7) and "ROI INTRUDER" label badge when line crossed or zone breached', async ({ page }) => {
    await page.route(/\/api\/v1\/cameras\/.*\/stream/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'image/jpeg',
        body: JPEG_1X1,
      })
    );
    await page.route('**/api/v1/watchlist', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    );
    await page.route('**/api/v1/models', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ models: [], active_model: '' }) })
    );

    // Mock cameras with active line fence
    await page.route('**/api/v1/cameras', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'c1',
            name: 'Perimeter Gate',
            endpoint: 'http://1.1.1.1/video',
            observed_state: 'STREAMING',
            stream_epoch: 1,
            fence: {
              polygon: [[0.1, 0.5], [0.9, 0.5]],
              fence_type: 'line',
              enabled: true,
              name: 'Tripwire Alpha',
            },
          },
        ]),
      })
    );

    // Mock observations with a person track flagged as an intrusion
    await page.route('**/api/v1/cameras/c1/observations', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          runtime: 'DirectML',
          tracks: [
            {
              track_id: 88,
              class_name: 'person',
              confidence: 0.93,
              bbox_norm: [0.4, 0.45, 0.6, 0.75],
              intrusion: true,
            },
          ],
          faces: [],
        }),
      })
    );

    await page.route('**/api/v1/events*', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    );
    await page.route('**/api/v1/health', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) })
    );
    await page.route('**/api/v1/cameras/*/health', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
    );

    await page.goto('/');

    const livePlayer = page.getByTestId('live-player-c1');
    await expect(livePlayer).toBeVisible();

    // 1. Verify "ROI INTRUDER" badge label is rendered in OverlayCanvas
    await expect(livePlayer.getByText('ROI INTRUDER')).toBeVisible();

    // 2. Verify purple outline box with data-testid="roi-intruder-box"
    const intruderBox = livePlayer.getByTestId('roi-intruder-box');
    await expect(intruderBox).toBeVisible();

    // 3. Verify stroke color is vibrant purple #a855f7
    await expect(intruderBox).toHaveAttribute('stroke', '#a855f7');
    await expect(intruderBox).toHaveAttribute('data-roi-intruder', 'true');
    await expect(intruderBox).toHaveAttribute('aria-label', 'ROI intruders with a purple outline');

    // 4. Verify parent group has purple filter glow
    const filterContainer = livePlayer.locator('svg g[filter="url(#roi-intruder-glow)"]');
    await expect(filterContainer).toBeVisible();

    // 5. Verify clicking intruder box opens Quick Inspector showing "ROI Intruder" badge
    await intruderBox.click({ force: true });
    const inspectorBadge = livePlayer.getByTestId('roi-intruder-inspector-badge');
    await expect(inspectorBadge).toBeVisible();
    await expect(inspectorBadge).toHaveText(/ROI Intruder/i);
  });
});
