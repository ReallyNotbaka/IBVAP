import { chromium } from '@playwright/test';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SCREENSHOT_DIR = path.resolve(__dirname, '../ui-inspection-output');

if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function runAllInspections() {
  console.log('=== STARTING DEEP INVESTIGATION OF IBVAP WEB APP ===');
  console.log('Target Server: http://localhost:8000');
  console.log('Output Directory:', SCREENSHOT_DIR);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  const consoleErrors = [];
  const networkErrors = [];

  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => {
    consoleErrors.push(`[PageError] ${err.message}`);
  });
  page.on('response', (res) => {
    if (res.status() >= 400) {
      networkErrors.push(`${res.status()} ${res.url()}`);
    }
  });

  // Mock observation feed so we have consistent detections and face tracks for HUD & Quick Inspector testing
  await page.route('**/api/v1/cameras/*/observations', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        runtime: 'DirectML',
        active_model: 'yolo26n',
        tracks: [
          {
            track_id: 104,
            class_name: 'person',
            confidence: 0.94,
            bbox_norm: [0.25, 0.2, 0.55, 0.75],
          },
        ],
        detections: [
          {
            class_name: 'person',
            confidence: 0.94,
            bbox_norm: [0.25, 0.2, 0.55, 0.75],
          },
        ],
        faces: [
          {
            confidence: 0.88,
            bbox_norm: [0.35, 0.22, 0.45, 0.38],
            quality_passed: true,
          },
        ],
        plates: [],
        night: {
          is_night: false,
          illumination_score: 120,
          motion_area: 0.1,
          confidence: 0.8,
          limitation: 'none',
        },
        frame_at: Date.now() / 1000,
      }),
    });
  });

  // Mock events if empty so AlertRail and drawer show realistic operational events
  await page.route('**/api/v1/events*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'ev-alert-101',
          camera_id: 'ff8b3a91-8ac3-4023-a211-39113fae0b80',
          event_type: 'perimeter_intrusion',
          confidence: 0.94,
          zone_id: 'Sector-North-Gate',
          created_at: Math.floor(Date.now() / 1000) - 30,
        },
        {
          id: 'ev-alert-102',
          camera_id: 'ff8b3a91-8ac3-4023-a211-39113fae0b80',
          event_type: 'vehicle_crossing',
          confidence: 0.89,
          zone_id: 'Checkpoint-Alpha',
          created_at: Math.floor(Date.now() / 1000) - 120,
        },
      ]),
    });
  });

  // Mock watchlist with sample profile so watchlist list tab displays enrolled profiles
  await page.route('**/api/v1/watchlist', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          entries: [
            {
              id: 'wl-target-001',
              name: 'Target Vikramaditya',
              threat_level: 'HIGH',
              notes: 'Flagged subject sighted near north gate perimeter.',
              created_at: Math.floor(Date.now() / 1000) - 86400,
              photo_count: 2,
              thumbnail_b64: '',
              sight_count: 3,
              last_sighted: Math.floor(Date.now() / 1000) - 1800,
            },
          ],
        }),
      });
    } else {
      await route.continue();
    }
  });

  // ----------------------------------------------------
  // AREA 1: Cockpit (/)
  // ----------------------------------------------------
  console.log('\n--- 1. Testing Cockpit (/) ---');
  await page.goto('http://localhost:8000/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);

  // Set to Dark Mode initially
  const isDarkInitial = await page.evaluate(() => document.documentElement.classList.contains('dark'));
  if (!isDarkInitial) {
    await page.getByTestId('theme-toggle').click();
    await page.waitForTimeout(400);
  }

  // 1a. Test Control Pill Bar Presets: Clean
  console.log('Testing "Clean" preset...');
  const cleanBtn = page.getByRole('button', { name: 'Clean', exact: true });
  await cleanBtn.click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_cockpit_dark_clean.png'), fullPage: true });

  // 1b. Test Control Pill Bar Presets: All Data (shows detections & face tracking)
  console.log('Testing "All Data" preset...');
  const allDataBtn = page.getByRole('button', { name: 'All Data', exact: true });
  await allDataBtn.click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_cockpit_dark_all_data.png'), fullPage: true });

  // 1c. Test Control Pill Bar Presets: Alerts Only
  console.log('Testing "Alerts Only" preset...');
  const alertsOnlyBtn = page.getByRole('button', { name: 'Alerts Only', exact: true });
  await alertsOnlyBtn.click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_cockpit_dark_alerts_only.png'), fullPage: true });

  // Switch back to All Data for toggles & inspector
  await allDataBtn.click();
  await page.waitForTimeout(300);

  // 1d. Test Individual Toggle Switches (People, Faces, Labels, % Conf)
  console.log('Testing individual toggle switches...');
  const facesToggle = page.getByRole('button', { name: /Faces/i });
  const confToggle = page.getByRole('button', { name: /Conf/i });

  // Toggle faces off
  await facesToggle.click();
  await page.waitForTimeout(200);
  // Toggle conf off
  await confToggle.click();
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_cockpit_pill_toggles.png'), fullPage: true });

  // Restore toggles
  await facesToggle.click();
  await confToggle.click();
  await page.waitForTimeout(300);

  // 1e. Test Quick Inspector: Click on detected subject
  console.log('Testing Quick Inspector by clicking on detected target...');
  const targetSvg = page.locator('svg g rect.cursor-pointer').first();
  await targetSvg.waitFor({ state: 'visible', timeout: 5000 });
  await targetSvg.click({ force: true });
  await page.waitForTimeout(400);
  const inspectorCard = page.locator('.inspector-card');
  await inspectorCard.waitFor({ state: 'visible', timeout: 3000 });
  const cardText = await inspectorCard.innerText();
  console.log('Inspector Card content:', cardText.replace(/\n+/g, ' | '));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '05_cockpit_quick_inspector.png') });

  // 1f. Test Solo Focus Mode: click expand ⤢ on camera tile
  console.log('Testing Solo Focus Mode...');
  // Close inspector card first
  await inspectorCard.getByRole('button', { name: '✕' }).click();
  await page.waitForTimeout(200);

  const expandBtn = page.getByRole('button', { name: /Expand to Theater Solo Mode/i }).first();
  await expandBtn.click();
  await page.waitForTimeout(400);
  const soloBanner = page.locator('button:has-text("Solo Focus:")');
  console.log('Solo Focus banner visible?:', await soloBanner.isVisible());
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '06_cockpit_solo_focus_mode.png'), fullPage: true });

  // Exit Solo Mode
  const exitSoloBtn = page.getByRole('button', { name: /Exit Solo/i }).or(soloBanner);
  await exitSoloBtn.first().click();
  await page.waitForTimeout(300);

  // 1g. Test Activity Drawer: Open and close right-hand Alerts & Watchlist drawer
  console.log('Testing Activity Drawer...');
  const drawerBtn = page.getByRole('button', { name: /Alerts/i }).last();
  await drawerBtn.click();
  await page.waitForTimeout(400);
  const drawerHeading = page.getByRole('heading', { name: /Alerts & Watchlist/i });
  console.log('Drawer opened?:', await drawerHeading.isVisible());
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '07_cockpit_activity_drawer.png'), fullPage: true });

  const closeDrawerBtn = page.getByRole('button', { name: 'Close Drawer' }).or(page.locator('.drawer-slide-animate button:has-text("✕")'));
  await closeDrawerBtn.first().click();
  await page.waitForTimeout(300);

  // ----------------------------------------------------
  // AREA 2: Alerts Page (/alerts)
  // ----------------------------------------------------
  console.log('\n--- 2. Testing Alerts Page (/alerts) ---');
  await page.goto('http://localhost:8000/alerts', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '08_alerts_page_dark.png'), fullPage: true });

  // Toggle to light mode on /alerts
  await page.getByTestId('theme-toggle').click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '09_alerts_page_light.png'), fullPage: true });

  // Switch back to dark
  await page.getByTestId('theme-toggle').click();
  await page.waitForTimeout(400);

  // ----------------------------------------------------
  // AREA 3: Health Diagnostics Page (/health)
  // ----------------------------------------------------
  console.log('\n--- 3. Testing Health Diagnostics Page (/health) ---');
  await page.goto('http://localhost:8000/health', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '10_health_page_dark.png'), fullPage: true });

  // Toggle to light mode on /health
  await page.getByTestId('theme-toggle').click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '11_health_page_light.png'), fullPage: true });

  // Switch back to dark
  await page.getByTestId('theme-toggle').click();
  await page.waitForTimeout(400);

  // ----------------------------------------------------
  // AREA 4: Connect Phone Camera (/connect/phone)
  // ----------------------------------------------------
  console.log('\n--- 4. Testing Connect Phone Camera (/connect/phone) ---');
  await page.goto('http://localhost:8000/connect/phone', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(500);

  // Step 1: Prepare phone
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '12_connect_phone_step1.png') });

  // Advance to Step 2: Enter connection
  const prepareDoneBtn = page.getByTestId('prepare-done');
  await prepareDoneBtn.click();
  await page.waitForTimeout(300);

  const streamInput = page.getByTestId('stream-url');
  await streamInput.fill('synthetic://phone-cam-test');
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '13_connect_phone_step2.png') });

  // Click "Test connection"
  const testConnectionBtn = page.getByRole('button', { name: /Test connection/i });
  await testConnectionBtn.click();
  console.log('Testing synthetic connection...');
  await page.waitForSelector('text=Confirm live preview', { timeout: 10000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '14_connect_phone_tested.png') });

  // Close Connect modal via Close button
  const closeConnectBtn = page.locator('button:has-text("Close")').or(page.locator('.modal-content-animate button:has-text("✕")'));
  await closeConnectBtn.first().click();
  await page.waitForTimeout(400);

  // ----------------------------------------------------
  // AREA 5: Use Video Footage (/use/footage)
  // ----------------------------------------------------
  console.log('\n--- 5. Testing Use Video Footage (/use/footage) ---');
  await page.goto('http://localhost:8000/use/footage', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '15_use_footage_page_dark.png'), fullPage: true });

  // Stage footage file
  const videoFilePath = path.resolve(__dirname, '../../data/test_upload_face.mp4');
  if (fs.existsSync(videoFilePath)) {
    console.log('Staging video file in footage upload form...');
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(videoFilePath);
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '15b_use_footage_file_staged.png'), fullPage: true });
  }

  // Toggle to light mode on /use/footage
  await page.evaluate(() => document.documentElement.classList.remove('dark'));
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '16_use_footage_page_light.png'), fullPage: true });

  // Back to dark mode
  await page.evaluate(() => document.documentElement.classList.add('dark'));
  await page.waitForTimeout(400);

  // ----------------------------------------------------
  // AREA 6: Dynamic Model Switcher Modal
  // ----------------------------------------------------
  console.log('\n--- 6. Testing Dynamic Model Switcher Modal ---');
  await page.goto('http://localhost:8000/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(600);

  const modelBtn = page.getByRole('button', { name: /⚡|Model:/i }).first();
  await modelBtn.click();
  await page.waitForSelector('text=Dynamic YOLO26 Neural Model Switcher');
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '17_model_modal_available.png') });

  // Click uninstalled model (yolo26s) to trigger confirmation prompt
  console.log('Triggering download prompt for uninstalled model (yolo26s)...');
  const downloadAndSwitchBtn = page.getByRole('button', { name: 'Download & Switch' }).first();
  await downloadAndSwitchBtn.click();
  await page.waitForSelector('text=Install Model Weights?');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '18_model_modal_confirm_download.png') });

  // Cancel download prompt
  const cancelDownloadBtn = page.getByRole('button', { name: 'Cancel' }).last();
  if (await cancelDownloadBtn.isVisible()) {
    await cancelDownloadBtn.click();
    await page.waitForTimeout(300);
  }

  // Switch to USB / Air-Gapped Tab
  console.log('Testing USB Air-Gapped Tab...');
  const usbTabBtn = page.getByRole('button', { name: /Air-Gapped \/ USB/i });
  await usbTabBtn.click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '19_model_modal_usb_airgap.png') });

  // Close model modal
  await page.locator('.modal-content-animate button:has-text("✕")').first().click();
  await page.waitForTimeout(300);

  // ----------------------------------------------------
  // AREA 7: Biometric Watchlist Modal
  // ----------------------------------------------------
  console.log('\n--- 7. Testing Biometric Watchlist Modal ---');
  const watchlistBtn = page.getByRole('button', { name: /🎯.*Watchlist/i }).first();
  await watchlistBtn.click();
  await page.waitForSelector('text=Biometric Watchlist');
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '20_watchlist_modal_enrolled.png') });

  // Switch to Enroll New Target Tab
  console.log('Testing Enroll New Target Tab & Priority Tiers...');
  const enrollTab = page.getByRole('button', { name: /\+ Enroll New Target/i });
  await enrollTab.click();
  await page.waitForTimeout(300);

  // Test selecting different threat priority tiers (e.g. CRITICAL)
  const criticalTierBtn = page.getByRole('button', { name: 'CRITICAL', exact: true });
  if (await criticalTierBtn.isVisible()) {
    await criticalTierBtn.click();
    await page.waitForTimeout(200);
  }
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '21_watchlist_modal_enroll_form.png') });

  // Close modal
  await page.locator('.modal-content-animate button:has-text("✕")').first().click();
  await page.waitForTimeout(300);

  // 7b. Test Quick Inspector "Put on Watchlist" button prefill workflow
  console.log('Testing Quick Inspector -> Watchlist modal prefill flow...');
  const targetSvg2 = page.locator('svg g rect.cursor-pointer').first();
  if (await targetSvg2.isVisible()) {
    await targetSvg2.click({ force: true });
    await page.waitForTimeout(400);
    const putOnWatchlistBtn = page.getByRole('button', { name: /Put on Watchlist/i });
    if (await putOnWatchlistBtn.isVisible()) {
      await putOnWatchlistBtn.click();
      await page.waitForTimeout(600);
      await page.screenshot({ path: path.join(SCREENSHOT_DIR, '22_watchlist_modal_quick_inspector_prefill.png') });
      await page.locator('.modal-content-animate button:has-text("✕")').first().click();
      await page.waitForTimeout(300);
    }
  }

  // ----------------------------------------------------
  // AREA 8: Animated Theme Engine
  // ----------------------------------------------------
  console.log('\n--- 8. Testing Animated Theme Engine ---');
  // Toggle to Light Mode on Cockpit
  const themeToggleBtn = page.getByTestId('theme-toggle');
  await themeToggleBtn.click();
  await page.waitForTimeout(450);

  const lightCockpitBg = await page.evaluate(() => window.getComputedStyle(document.body).backgroundColor);
  console.log('Light Cockpit body background:', lightCockpitBg);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '23_cockpit_light_theme.png'), fullPage: true });

  // Capture close-up of the Theme Toggle morphing icon
  await themeToggleBtn.screenshot({ path: path.join(SCREENSHOT_DIR, '24_theme_icon_morph.png') });

  // Check for any radial-gradient or AI-slop
  const gradientStyles = await page.evaluate(() => {
    const all = Array.from(document.querySelectorAll('*'));
    return all
      .map((el) => window.getComputedStyle(el).backgroundImage)
      .filter((bg) => bg && (bg.includes('radial-gradient') || bg.includes('linear-gradient(to right, rgb(147, 51, 234)')));
  });
  console.log('Forbidden gradient count:', gradientStyles.length);

  // Transition validation
  const bodyTransition = await page.evaluate(() => window.getComputedStyle(document.body).transition);
  console.log('Body CSS transition:', bodyTransition);

  console.log('\n=== COMPREHENSIVE INVESTIGATION SUMMARY ===');
  console.log('Total Console Errors:', consoleErrors.length);
  if (consoleErrors.length > 0) consoleErrors.forEach((e) => console.log('  [Console Error]', e));
  console.log('Total Network Errors (>=400):', networkErrors.length);
  if (networkErrors.length > 0) networkErrors.forEach((e) => console.log('  [Network Error]', e));

  const savedFiles = fs.readdirSync(SCREENSHOT_DIR);
  console.log(`Saved ${savedFiles.length} screenshots to ${SCREENSHOT_DIR}:`);
  savedFiles.forEach((f) => console.log(`  - ${f}`));

  await browser.close();
  console.log('All inspections completed successfully.');
}

runAllInspections().catch((err) => {
  console.error('INVESTIGATION SCRIPT FAILED:', err);
  process.exit(1);
});
