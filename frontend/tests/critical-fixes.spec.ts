import { test, expect, type Page } from '@playwright/test';
import * as fs from 'node:fs';

test.use({ acceptDownloads: true });

const PNG_1PX = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
);

const CAM_A = { id: 'cam-a', name: 'Cam A', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 };
const CAM_B = { id: 'cam-b', name: 'Cam B', endpoint: 'http://1.1.1.2/video', observed_state: 'STREAMING', stream_epoch: 1 };

async function mockBase(page: Page): Promise<void> {
  await page.route('**/api/v1/events*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  );
  await page.route('**/api/v1/health', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }),
  );
  await page.route('**/api/v1/cameras/*/health', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }),
  );
  await page.route('**/api/v1/watchlist', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  );
  await page.route('**/api/v1/cameras/*/observations', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ tracks: [], detections: [], faces: [] }),
    }),
  );
}

test('revokes object URLs on remove', async ({ page }) => {
  await page.addInitScript(() => {
    (window as unknown as { __created: string[] }).__created = [];
    (window as unknown as { __revoked: string[] }).__revoked = [];
    const origCreate = URL.createObjectURL.bind(URL);
    const origRevoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = ((obj: Blob | MediaSource) => {
      const url = origCreate(obj as Blob);
      (window as unknown as { __created: string[] }).__created.push(url);
      return url;
    }) as typeof URL.createObjectURL;
    URL.revokeObjectURL = ((url: string) => {
      (window as unknown as { __revoked: string[] }).__revoked.push(url);
      origRevoke(url);
    }) as typeof URL.revokeObjectURL;
  });
  await page.route('**/api/v1/cameras', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([CAM_A]) }),
  );
  await mockBase(page);
  await page.goto('/');
  await page.getByTestId('topbar-watchlist-btn').click();
  await page.getByRole('button', { name: /enroll new target/i }).click();
  await page
    .locator('input[type="file"]')
    .setInputFiles([{ name: 'face.jpg', mimeType: 'image/jpeg', buffer: PNG_1PX }]);
  await expect(page.locator('img[alt="preview"]')).toHaveCount(1);
  const created = await page.evaluate(
    () => (window as unknown as { __created: string[] }).__created,
  );
  expect(created.length).toBeGreaterThanOrEqual(1);
  await page.locator('button[aria-label="Remove photo"]').first().click({ force: true });
  await expect(page.locator('img[alt="preview"]')).toHaveCount(0);
  const revoked = await page.evaluate(
    () => (window as unknown as { __revoked: string[] }).__revoked,
  );
  expect(revoked).toContain(created[0]);
});

test('calibration uses selected camera after load', async ({ page }) => {
  await page.route('**/api/v1/cameras', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([CAM_A, CAM_B]) }),
  );
  await mockBase(page);
  await page.route('**/api/v1/cameras/*/stream*', (route) =>
    route.fulfill({ status: 200, contentType: 'image/png', body: PNG_1PX }),
  );
  await page.route('**/api/v1/tactical/radar', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ max_range_m: 100, range_rings_m: [10, 25, 50], cameras: [], blips: [] }),
    }),
  );
  let postedBody: { camera_id?: string } | null = null;
  await page.route('**/api/v1/tactical/radar/calibrate', async (route) => {
    try {
      postedBody = JSON.parse(route.request().postData() || '{}');
    } catch {
      postedBody = null;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok', camera_id: (postedBody as { camera_id?: string } | null)?.camera_id ?? '' }),
    });
  });
  await page.goto('/');
  await expect(page.getByTestId('live-player-cam-b')).toBeVisible();
  // Select camera B on the cockpit, then open calibration for it.
  await page.getByTestId('live-player-cam-b').click();
  await page.getByRole('button', { name: /bev radar/i }).click();
  await page.getByRole('button', { name: /calibrate camera/i }).click();
  const camSelect = page.locator('select', { has: page.locator('option[value="cam-b"]') });
  await expect(camSelect).toBeVisible();
  await expect(camSelect).toHaveValue('cam-b');
  await page.getByRole('button', { name: /apply & save calibration/i }).click();
  await expect.poll(() => postedBody?.camera_id, { timeout: 5000 }).toBe('cam-b');
});

test('CSV escapes formulas', async ({ page }) => {
  const evil = '=1+1';
  const now = Math.floor(Date.now() / 1000);
  await page.route('**/api/v1/cameras', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([CAM_A]) }),
  );
  await mockBase(page);
  await page.route('**/api/v1/events*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'e-evil',
          event_type: 'watchlist_match',
          camera_id: 'cam-a',
          zone_id: 'z1',
          track_id: 7,
          confidence: 0.9,
          created_at: now,
          explanation: { suspect_name: evil, threat_level: 'HIGH' },
        },
      ]),
    }),
  );
  await page.goto('/alerts');
  const exportBtn = page.getByRole('button', { name: /export csv/i });
  await expect(exportBtn).toBeEnabled();
  const [download] = await Promise.all([page.waitForEvent('download'), exportBtn.click()]);
  const filePath = await download.path();
  expect(filePath).toBeTruthy();
  const csv = fs.readFileSync(filePath as string, 'utf8');
  expect(csv).toContain(`"'${evil}"`);
});

test('seek commits once on release (debounced)', async ({ page }) => {
  const footage = {
    ...CAM_A,
    id: 'c1',
    name: 'Footage 1',
    source_type: 'video_footage',
    protocol: 'file',
  };
  const seeks: number[] = [];
  await page.route('**/api/v1/cameras', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([footage]) }),
  );
  await mockBase(page);
  await page.route('**/api/v1/cameras/*/stream*', (route) =>
    route.fulfill({ status: 200, contentType: 'image/png', body: PNG_1PX }),
  );
  await page.route('**/api/v1/cameras/c1/playback', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ state: 'playing', position_seconds: 5, duration_seconds: 100, fps: 25 }),
    }),
  );
  await page.route('**/api/v1/cameras/c1/playback/seek', async (route) => {
    try {
      seeks.push(JSON.parse(route.request().postData() || '{}').position_seconds);
    } catch {
      /* ignore */
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ state: 'playing', position_seconds: 30, duration_seconds: 100, fps: 25 }),
    });
  });
  await page.route('**/api/v1/cameras/c1/playback/pause', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ state: 'paused', position_seconds: 5, duration_seconds: 100, fps: 25 }),
    }),
  );
  await page.route('**/api/v1/cameras/c1/playback/resume', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ state: 'playing', position_seconds: 30, duration_seconds: 100, fps: 25 }),
    }),
  );
  await page.goto('/');
  const slider = page.getByLabel('Seek footage');
  await expect(slider).toBeVisible();
  for (const v of ['10', '20', '30']) {
    await slider.evaluate((el: HTMLInputElement, val: string) => {
      // Bypass React's value tracker so the input event registers as a change.
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!
        .set!.call(el, val);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }, v);
  }
  // Release via keyboard commit (trusted, bubbling key events), as a user would
  // after arrow-key seeking. Synthetic mouseup does not reach React 19's
  // root listener, so keyboard is the deterministic release path here.
  await slider.press('Enter');
  await expect.poll(() => seeks.length, { timeout: 8000 }).toBe(1);
  expect(seeks[0]).toBe(30);
});

test('MJPEG tile retries with cache-busted URL after error', async ({ page }) => {
  let streamHits = 0;
  await page.route('**/api/v1/cameras', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([CAM_A]) }),
  );
  await mockBase(page);
  await page.route('**/api/v1/cameras/*/stream*', (route) => {
    streamHits += 1;
    return route.abort();
  });
  await page.goto('/');
  await expect(page.getByTestId('live-player-cam-a')).toBeVisible();
  await expect.poll(() => streamHits, { timeout: 12000 }).toBeGreaterThanOrEqual(2);
});

test('alerts render paginated /events envelope', async ({ page }) => {
  const now = Math.floor(Date.now() / 1000);
  await page.route('**/api/v1/cameras', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([CAM_A]) }),
  );
  await mockBase(page);
  await page.route('**/api/v1/events*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            id: 'e1',
            event_type: 'intrusion',
            camera_id: 'cam-a',
            zone_id: 'z1',
            confidence: 0.8,
            created_at: now,
          },
        ],
        total: 1,
      }),
    }),
  );
  await page.goto('/alerts');
  await expect(page.locator('body')).toContainText('Zone: z1');
});

test('tile tolerates missing health telemetry without fabricating', async ({ page }) => {
  await page.route('**/api/v1/cameras', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([CAM_A]) }),
  );
  await mockBase(page);
  await page.route('**/api/v1/cameras/*/stream*', (route) =>
    route.fulfill({ status: 200, contentType: 'image/png', body: PNG_1PX }),
  );
  await page.goto('/');
  const tile = page.getByTestId('live-player-cam-a');
  await expect(tile).toBeVisible();
  await expect(tile).toContainText('--');
});

test('single Backspace removes exactly one fence point', async ({ page }) => {
  await page.route('**/api/v1/cameras', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([CAM_A]) }),
  );
  await mockBase(page);
  await page.route('**/api/v1/cameras/*/stream*', (route) =>
    route.fulfill({ status: 200, contentType: 'image/png', body: PNG_1PX }),
  );
  await page.goto('/');
  await page.getByRole('button', { name: /draw fence/i }).click();
  const tile = page.getByTestId('live-player-cam-a');
  for (const fx of [0.35, 0.5, 0.65]) {
    await tile.scrollIntoViewIfNeeded();
    const box = await tile.boundingBox();
    expect(box).toBeTruthy();
    const b = box as { x: number; y: number; width: number; height: number };
    await page.mouse.click(b.x + b.width * fx, b.y + b.height * 0.55);
    await page.waitForTimeout(400);
  }
  await expect(page.getByText('3 pts')).toBeVisible();
  await page.keyboard.press('Backspace');
  await expect(page.getByText('2 pts')).toBeVisible();
});
