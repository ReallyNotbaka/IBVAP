import { chromium } from '@playwright/test';
import path from 'path';

const SCREENSHOT_DIR = 'C:/Users/ReallyNotBaka/.gemini/antigravity-cli/brain/ccb754e6-5f9d-43de-904e-806e95585800/screenshots';

async function main() {
  console.log('[Playwright Inspector] Launching Chromium browser...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
  });
  const page = await context.newPage();

  const consoleLogs = [];
  const networkErrors = [];

  page.on('console', (msg) => {
    consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
  });

  page.on('pageerror', (err) => {
    console.error('[Page Error]:', err.message);
  });

  page.on('response', (res) => {
    if (res.status() >= 400) {
      networkErrors.push(`${res.status()} ${res.url()}`);
    }
  });

  // 1. Overview / Landing Page
  console.log('[1/5] Navigating to Overview / Landing Page (http://127.0.0.1:8000/)...');
  await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });
  const homeTitle = await page.title();
  console.log(`      Title: "${homeTitle}"`);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_home_page.png'), fullPage: true });

  // 2. Connect Phone Camera Wizard Step 1 & 2
  console.log('[2/5] Navigating to Phone Camera Wizard (/connect/phone)...');
  await page.goto('http://127.0.0.1:8000/connect/phone', { waitUntil: 'networkidle' });
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_connect_phone_step1.png'), fullPage: true });

  // Click "My phone camera is running"
  const prepButton = page.locator('button[data-testid="prepare-done"], button:has-text("My phone camera is running")');
  if (await prepButton.isVisible()) {
    console.log('      Clicking "My phone camera is running"...');
    await prepButton.click();
    await page.waitForTimeout(300);

    const streamUrlInput = page.locator('input').first();
    if (await streamUrlInput.isVisible()) {
      console.log('      Typing RTSP endpoint into stream URL field...');
      await streamUrlInput.fill('rtsp://192.168.1.120:8080/h264_pcm.sdp');
      await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_connect_phone_step2_filled.png'), fullPage: true });

      // Click "Test connection"
      const testButton = page.locator('button:has-text("Test connection")');
      if (await testButton.isVisible()) {
        console.log('      Clicking "Test connection" button...');
        await testButton.click();
        await page.waitForTimeout(1500);
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_connect_phone_tested.png'), fullPage: true });
      }
    }

  }

  // 3. Monitor View
  console.log('[3/5] Navigating to Surveillance Monitor (/monitor)...');
  await page.goto('http://127.0.0.1:8000/monitor', { waitUntil: 'networkidle' });
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_surveillance_monitor.png'), fullPage: true });

  // 4. Alerts Inbox
  console.log('[4/5] Navigating to Alerts Inbox (/alerts)...');
  await page.goto('http://127.0.0.1:8000/alerts', { waitUntil: 'networkidle' });
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '05_alerts_inbox.png'), fullPage: true });

  // 5. System Health Status
  console.log('[5/5] Navigating to Health & Diagnostics (/health)...');
  await page.goto('http://127.0.0.1:8000/health', { waitUntil: 'networkidle' });
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '06_system_health.png'), fullPage: true });

  console.log('\n[Inspection Summary]');
  console.log(`Total Console Messages: ${consoleLogs.length}`);
  consoleLogs.slice(0, 5).forEach((log) => console.log('  ', log));
  console.log(`Total Network Errors: ${networkErrors.length}`);
  networkErrors.forEach((err) => console.log('  ', err));

  await browser.close();
  console.log('[Playwright Inspector] All pages inspected with form interactions and screenshots saved.');
}

main().catch((err) => {
  console.error('[Playwright Error]:', err);
  process.exit(1);
});
