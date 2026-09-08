import { test, expect } from '@playwright/test';
import path from 'path';

test.describe('Visual Inspection & Bespoke Polish Suite', () => {
  test('inspects Cockpit, Video Overlay, Quick Inspector, Watchlist & Model Modals in Dark and Light Modes', async ({ page }) => {
    // Setup rich mocks
    await page.route('**/api/v1/cameras/*/stream*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'image/jpeg',
        body: Buffer.from('data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7', 'base64'),
      })
    );
    await page.route('**/api/v1/models', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    );
    await page.route('**/api/v1/cameras', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'c1', name: 'Main Entrance Sensor', endpoint: 'http://1.1.1.1/video', observed_state: 'STREAMING', stream_epoch: 1 },
        ]),
      })
    );
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
    await page.route('**/api/v1/events*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'ev1', camera_id: 'c1', event_type: 'intrusion', confidence: 0.95, zone_id: 'North Gate' },
          { id: 'ev2', camera_id: 'c1', event_type: 'perimeter_crossed', confidence: 0.89 },
        ]),
      })
    );
    await page.route('**/api/v1/watchlist', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'wl1', name: 'Target Alpha', category: 'High Priority Alert', notes: 'Subject observed near perimeter' },
        ]),
      })
    );
    await page.route('**/api/v1/health', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', storage_pressure: 'Normal', queue_drops: 0 }) })
    );
    await page.route('**/api/v1/cameras/*/health', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ last_frame_age_ms: 80, analysis_fps: 15, inference_ms: 14 }) })
    );

    await page.goto('/');

    // 1. Verify Topbar and theme
    const topbar = page.locator('header.topbar');
    await expect(topbar).toBeVisible();

    // Ensure Dark Mode initially
    const isDark = await page.evaluate(() => document.documentElement.classList.contains('dark'));
    if (!isDark) {
      await page.getByTestId('theme-toggle').click();
    }
    await page.waitForTimeout(1200);

    // Verify dark theme body background and absence of purple gradients
    const darkBg = await page.evaluate(() => window.getComputedStyle(document.body).backgroundColor);
    // Dark mode body is architectural neutral graphite #151515 or obsidian #0c0e12 / #0b0d11
    expect(['rgb(11, 13, 17)', 'rgb(12, 14, 18)', 'rgb(21, 21, 21)']).toContain(darkBg);

    // Verify overlay corner brackets and stroke
    const cornerPath = page.locator('svg path[stroke="#e8dfd2"], svg path[stroke="#dfd5c6"]').first();
    await expect(cornerPath).toBeVisible();

    // Verify Quick Inspector on target click (Dark Mode)
    const targetHit = page.locator('svg g rect.cursor-pointer').first();
    await expect(targetHit).toBeVisible();
    await targetHit.click({ force: true });

    const inspectorCard = page.locator('.inspector-card');
    await expect(inspectorCard).toBeVisible();
    await expect(inspectorCard).toContainText(/person/i);
    await expect(inspectorCard).toContainText('#104');
    await expect(inspectorCard).toContainText('94%');

    await page.screenshot({
      path: path.resolve('ui-inspection-output/inspector_dark.png'),
    });

    // Close inspector card
    await inspectorCard.getByRole('button', { name: /close|✕/i }).click();
    await expect(inspectorCard).not.toBeVisible();

    // Dark Mode Model Modal
    const modelBtnDark = page.getByTestId('topbar-model-btn');
    await modelBtnDark.click();
    const modelModalDark = page.getByRole('heading', { name: /Dynamic YOLO26 Neural Model Switcher/i });
    await expect(modelModalDark).toBeVisible();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.resolve('ui-inspection-output/model_modal_dark.png'),
    });
    const modelContainerDark = page.locator('.modal-content-animate');
    await modelContainerDark.getByRole('button', { name: /close|✕/i }).click();
    await expect(modelModalDark).not.toBeVisible();

    // Dark Mode Watchlist Modal
    const watchlistBtnDark = page.getByTestId('topbar-watchlist-btn');
    await watchlistBtnDark.click();
    const watchlistModalDark = page.getByRole('heading', { name: /Biometric Watchlist/i });
    await expect(watchlistModalDark).toBeVisible();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.resolve('ui-inspection-output/watchlist_modal_dark.png'),
    });
    const watchlistContainerDark = page.locator('.modal-content-animate');
    await watchlistContainerDark.getByRole('button', { name: /close|✕/i }).click();
    await expect(watchlistModalDark).not.toBeVisible();

    // Dark Mode Drawer
    const drawerBtnDark = page.getByRole('button', { name: /Alerts/i }).filter({ hasText: 'Alerts' }).last();
    await drawerBtnDark.click();
    await expect(page.getByRole('heading', { name: /Alerts & (Watchlist|Suspects)/i })).toBeVisible();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.resolve('ui-inspection-output/drawer_dark.png'),
    });
    await page.getByRole('button', { name: 'Close Drawer' }).click();
    await expect(page.getByRole('heading', { name: /Alerts & (Watchlist|Suspects)/i })).not.toBeVisible();

    // 2. Switch to Light Mode
    await page.getByTestId('theme-toggle').click();
    await page.waitForTimeout(1200);
    await page.waitForFunction(() => window.getComputedStyle(document.body).backgroundColor === 'rgb(250, 250, 250)', { timeout: 3000 });

    const lightBg = await page.evaluate(() => window.getComputedStyle(document.body).backgroundColor);
    console.log('Light mode body backgroundColor:', lightBg);
    expect(lightBg).toBe('rgb(250, 250, 250)');

    // Verify theme toggle animation classes / attributes
    const themeBtn = page.getByTestId('theme-toggle');
    await expect(themeBtn).toBeVisible();

    // Light Mode Quick Inspector
    await page.evaluate(() => window.scrollTo(0, 0));
    await targetHit.click({ force: true });
    await expect(inspectorCard).toBeVisible();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.resolve('ui-inspection-output/inspector_light.png'),
    });
    await inspectorCard.getByRole('button', { name: /close|✕/i }).click();
    await expect(inspectorCard).not.toBeVisible();

    // 3. Test Watchlist Modal in Light Mode
    const watchlistBtn = page.getByTestId('topbar-watchlist-btn');
    await watchlistBtn.click();
    const watchlistModal = page.getByRole('heading', { name: /Biometric Watchlist/i });
    await expect(watchlistModal).toBeVisible();
    await expect(page.getByRole('button', { name: /Targets Enrolled/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Enroll New Target/i })).toBeVisible();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.resolve('ui-inspection-output/watchlist_modal_light.png'),
    });

    // Close modal via modal's close button
    const watchlistContainer = page.locator('.modal-content-animate');
    await watchlistContainer.getByRole('button', { name: /close|✕/i }).click();
    await expect(watchlistModal).not.toBeVisible();

    // 4. Test Model Selector Modal in Light Mode
    const modelBtn = page.getByTestId('topbar-model-btn');
    await modelBtn.click();
    const modelModal = page.getByRole('heading', { name: /Dynamic YOLO26 Neural Model Switcher/i });
    await expect(modelModal).toBeVisible();
    await expect(page.getByRole('button', { name: /Available Models/i })).toBeVisible();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.resolve('ui-inspection-output/model_modal_light.png'),
    });

    // Close modal via modal's close button
    const modelContainer = page.locator('.modal-content-animate');
    await modelContainer.getByRole('button', { name: /close|✕/i }).click();
    await expect(modelModal).not.toBeVisible();

    // 5. Test Control Pill Bar in Light Mode
    const cleanPreset = page.getByRole('button', { name: 'Clean' });
    const allDataPreset = page.getByRole('button', { name: 'All Data' });
    const alertsOnlyPreset = page.getByRole('button', { name: 'Alerts Only' });
    await expect(cleanPreset).toBeVisible();
    await expect(allDataPreset).toBeVisible();
    await expect(alertsOnlyPreset).toBeVisible();

    await cleanPreset.click();
    await allDataPreset.click();

    // Verify drawer toggle in Light Mode
    const drawerBtn = page.getByRole('button', { name: /Alerts/i }).filter({ hasText: 'Alerts' }).last();
    await drawerBtn.click();
    await expect(page.getByRole('heading', { name: /Alerts & (Watchlist|Suspects)/i })).toBeVisible();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.resolve('ui-inspection-output/drawer_light.png'),
    });
    await page.getByRole('button', { name: 'Close Drawer' }).click();
    await expect(page.getByRole('heading', { name: /Alerts & (Watchlist|Suspects)/i })).not.toBeVisible();

    // 6. Test Alerts Page in Light & Dark Mode
    await page.goto('/alerts');
    await page.screenshot({
      path: path.resolve('ui-inspection-output/alerts_light.png'),
    });
    await page.getByTestId('theme-toggle').click();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.resolve('ui-inspection-output/alerts_dark.png'),
    });

    // 7. Test Health Page in Dark & Light Mode
    await page.goto('/health');
    await page.screenshot({
      path: path.resolve('ui-inspection-output/health_dark.png'),
    });
    await page.getByTestId('theme-toggle').click();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.resolve('ui-inspection-output/health_light.png'),
    });

    console.log('All visual inspection checks passed successfully!');
  });

  test('captures live screenshots and verifies zero duplicated options in EmptyState, UseFootage, and Cockpit', async ({ page }) => {
    // 1. Onboarding EmptyState (zero cameras)
    await page.route('**/api/v1/cameras', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/events*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/watchlist', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
    await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }));

    await page.goto('/');

    // Ensure Dark Mode
    const isDarkInitial = await page.evaluate(() => document.documentElement.classList.contains('dark'));
    if (!isDarkInitial) {
      await page.getByTestId('theme-toggle').click();
      await page.waitForTimeout(350);
    }

    // Verify exactly ONE Topbar and ZERO duplicate inner headers
    await expect(page.locator('header.topbar')).toHaveCount(1);
    await expect(page.locator('header:not(.topbar)')).toHaveCount(0);
    await expect(page.getByTestId('topbar-model-btn')).toHaveCount(1);
    await expect(page.getByTestId('topbar-watchlist-btn')).toHaveCount(1);
    await expect(page.getByTestId('theme-toggle')).toHaveCount(1);
    await expect(page.getByTestId('cta-connect-phone-topbar')).toHaveCount(1);
    await expect(page.locator('button[data-testid*="cta-connect-phone-topbar"]')).toHaveCount(1);

    // Empty state CTA is clearly visible
    await expect(page.getByTestId('cta-connect-phone')).toBeVisible();
    await expect(page.getByTestId('cta-use-footage')).toBeVisible();

    // Capture EmptyState Dark Mode screenshot
    await page.screenshot({
      path: path.resolve('ui-inspection-output/emptystate_dark.png'),
      fullPage: true,
    });

    // Switch to Light Mode
    await page.getByTestId('theme-toggle').click();
    await page.waitForTimeout(350);

    // Capture EmptyState Light Mode screenshot
    await page.screenshot({
      path: path.resolve('ui-inspection-output/emptystate_light.png'),
      fullPage: true,
    });

    // 2. Connect Modal in Light & Dark Mode
    await page.goto('/connect/phone');
    await expect(page.getByRole('heading', { name: /Connect Camera Source/i })).toBeVisible();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.resolve('ui-inspection-output/connect_modal_light.png'),
    });
    const connectContainer = page.locator('.modal-content-animate');
    await connectContainer.getByRole('button', { name: /close|✕/i }).first().click();
    await expect(page.locator('.modal-content-animate')).not.toBeVisible();

    // Switch to dark and open modal again
    await page.getByTestId('theme-toggle').click();
    await page.waitForTimeout(350);
    await page.goto('/connect/phone');
    await expect(page.getByRole('heading', { name: /Connect Camera Source/i })).toBeVisible();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.resolve('ui-inspection-output/connect_modal_dark.png'),
    });
    await page.locator('.modal-content-animate').getByRole('button', { name: /close|✕/i }).first().click();
    await expect(page.locator('.modal-content-animate')).not.toBeVisible();

    // Switch back to light for subsequent tests or continue
    await page.getByTestId('theme-toggle').click();
    await page.waitForTimeout(350);

    // 3. Use Footage page
    await page.goto('/use/footage');
    await expect(page.locator('header.topbar')).toHaveCount(1);
    await expect(page.locator('header:not(.topbar)')).toHaveCount(0);

    // Capture Use Footage Light Mode screenshot
    await page.screenshot({
      path: path.resolve('ui-inspection-output/usefootage_light.png'),
      fullPage: true,
    });

    // Switch to Dark Mode
    await page.getByTestId('theme-toggle').click();
    await page.waitForTimeout(350);

    // Capture Use Footage Dark Mode screenshot
    await page.screenshot({
      path: path.resolve('ui-inspection-output/usefootage_dark.png'),
      fullPage: true,
    });

    // 3. Cockpit with camera feed
    await page.route('**/api/v1/cameras', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'c1', name: 'Main Gate Camera', endpoint: 'http://192.168.1.100:8080/video', observed_state: 'STREAMING', stream_epoch: 1 },
        ]),
      })
    );
    await page.route('**/api/v1/cameras/*/health', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ last_frame_age_ms: 65, analysis_fps: 20, inference_ms: 12 }) })
    );

    await page.goto('/');
    await expect(page.locator('header.topbar')).toHaveCount(1);
    await expect(page.locator('header:not(.topbar)')).toHaveCount(0);
    await expect(page.getByTestId('topbar-model-btn')).toHaveCount(1);
    await expect(page.getByTestId('topbar-watchlist-btn')).toHaveCount(1);
    await expect(page.getByTestId('cta-connect-phone-topbar')).toHaveCount(1);
    await expect(page.locator('button[data-testid*="cta-connect-phone-topbar"]')).toHaveCount(1);

    // Verify control pill bar has NO duplicate Model or Watchlist buttons
    await expect(page.locator('.control-pill-bar')).toBeVisible();
    await expect(page.locator('.control-pill-bar').getByRole('button', { name: /Watchlist/i })).toHaveCount(0);
    await expect(page.locator('.control-pill-bar').getByRole('button', { name: /YOLO/i })).toHaveCount(0);

    // Capture Cockpit Dark Mode screenshot
    await page.screenshot({
      path: path.resolve('ui-inspection-output/cockpit_dark.png'),
      fullPage: true,
    });

    // Switch to Light Mode
    await page.getByTestId('theme-toggle').click();
    await page.waitForTimeout(350);

    // Capture Cockpit Light Mode screenshot
    await page.screenshot({
      path: path.resolve('ui-inspection-output/cockpit_light.png'),
      fullPage: true,
    });

    console.log('All verification screenshots captured successfully in ui-inspection-output!');
  });
});
