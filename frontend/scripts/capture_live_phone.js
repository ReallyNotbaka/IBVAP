import { chromium } from '@playwright/test';
import path from 'path';

const SCREENSHOT_DIR = 'C:/Users/ReallyNotBaka/.gemini/antigravity-cli/brain/ccb754e6-5f9d-43de-904e-806e95585800/screenshots';

async function main() {
  console.log('[Live Phone Inspector] Launching browser...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
  });
  const page = await context.newPage();

  page.on('console', (msg) => console.log(`[Browser Console]: ${msg.text()}`));
  page.on('pageerror', (err) => console.error(`[Browser PageError]: ${err.message}`));

  // 1. Visit Connect Phone wizard and test the stream
  console.log('[1/2] Opening Connect Phone wizard (/connect/phone)...');
  await page.goto('http://127.0.0.1:8000/connect/phone', { waitUntil: 'networkidle' });

  // Click "My phone camera is running"
  const prepButton = page.locator('button:has-text("My phone camera is running")');
  if (await prepButton.isVisible()) {
    await prepButton.click();
    await page.waitForTimeout(300);

    const streamInput = page.locator('input').first();
    await streamInput.fill('http://10.53.109.95:4747/video');

    const testButton = page.locator('button:has-text("Test connection")');
    await testButton.click();
    console.log('Testing live phone camera stream...');

    // Wait for the test result and probe
    await page.waitForSelector('text=Confirm live preview', { timeout: 10000 });
    console.log('Stream probed successfully! Capturing preview screenshot...');
    await page.waitForTimeout(2000); // give 2 seconds for live video frame to render
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '07_phone_wizard_live_preview.png'), fullPage: true });
  }

  // 2. Visit Monitoring Workspace with live camera feed
  console.log('[2/2] Opening Monitoring Workspace (/monitor)...');
  await page.goto('http://127.0.0.1:8000/monitor', { waitUntil: 'networkidle' });
  console.log('Waiting for live monitoring player to render...');
  await page.waitForTimeout(3000); // allow video stream frames to stream
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '08_monitor_live_phone_stream.png'), fullPage: true });

  await browser.close();
  console.log('[Live Phone Inspector] Done! Screenshots saved to:', SCREENSHOT_DIR);
}

main().catch((err) => {
  console.error('[Error]:', err);
  process.exit(1);
});
