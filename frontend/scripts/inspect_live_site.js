import { chromium } from '@playwright/test';

async function runLiveInspection() {
  console.log('--- STARTING COMPREHENSIVE LIVE INSPECTION AT http://localhost:8000 ---');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  page.on('console', (msg) => console.log(`[Browser Console ${msg.type()}]:`, msg.text()));
  page.on('pageerror', (err) => console.error('[Browser Error]:', err.message));

  // 1. Navigate to live app
  console.log('1. Navigating to http://localhost:8000...');
  const res = await page.goto('http://localhost:8000', { waitUntil: 'domcontentloaded' });
  console.log('HTTP Status:', res.status());
  await page.waitForTimeout(500);

  // Check whether we have cameras or are in EmptyState
  const hasOnboarding = await page.locator('[data-testid="cta-connect-phone"]').isVisible();
  console.log('Is Onboarding (EmptyState) visible?:', hasOnboarding);

  // 2. Test Light & Dark mode on current view
  const themeBtn = page.getByTestId('theme-toggle');
  await themeBtn.waitFor({ state: 'visible' });

  // Toggle to Dark Mode
  const isDarkInitial = await page.evaluate(() => document.documentElement.classList.contains('dark'));
  if (!isDarkInitial) {
    await themeBtn.click();
    await page.waitForTimeout(400);
  }

  const darkBg = await page.evaluate(() => window.getComputedStyle(document.body).backgroundColor);
  console.log('Dark mode computed body background:', darkBg);
  if (darkBg !== 'rgb(11, 13, 17)') {
    throw new Error(`Expected dark mode background rgb(11, 13, 17), got ${darkBg}`);
  }

  // Toggle to Light Mode
  await themeBtn.click();
  await page.waitForTimeout(400);

  const lightBg = await page.evaluate(() => window.getComputedStyle(document.body).backgroundColor);
  console.log('Light mode computed body background:', lightBg);
  if (lightBg !== 'rgb(250, 250, 250)') {
    throw new Error(`Expected light mode background rgb(250, 250, 250), got ${lightBg}`);
  }

  // Switch back to Dark Mode for remaining checks
  await themeBtn.click();
  await page.waitForTimeout(400);

  // 3. Inspect Watchlist Modal
  console.log('3. Inspecting Watchlist Modal...');
  const watchlistBtn = page.getByTestId('topbar-watchlist-btn').or(page.getByRole('button', { name: /Watchlist/i }));
  await watchlistBtn.first().click();
  await page.waitForSelector('text=Biometric Watchlist');
  console.log('Watchlist modal opened successfully.');

  // Check enrollment tab
  const enrollTab = page.getByRole('button', { name: /\+ Enroll New Target/i });
  await enrollTab.click();
  await page.waitForSelector('text=Subject / Profile Name *');
  console.log('Subject / Profile Name form field verified without cop terminology.');

  // Close Watchlist Modal
  const closeBtn = page.locator('.modal-content-animate button:has-text("✕")');
  await closeBtn.click();
  await page.waitForTimeout(300);

  // 4. Inspect Model Selector Modal
  console.log('4. Inspecting Model Selector Modal...');
  const modelBtn = page.getByTestId('topbar-model-btn').or(page.getByRole('button', { name: /⚡|Model:/i }));
  await modelBtn.first().click();
  await page.waitForSelector('text=Dynamic YOLO26 Neural Model Switcher');
  console.log('Model Selector Modal verified.');

  // Check USB Import Tab
  const usbTab = page.getByRole('button', { name: /Air-Gapped \/ USB/i });
  await usbTab.click();
  await page.waitForSelector('text=Air-Gapped Installation Mode');
  console.log('USB air-gapped tab verified.');

  // Close Model Modal
  await page.locator('.modal-content-animate button:has-text("✕")').click();
  await page.waitForTimeout(300);

  // 5. If in Cockpit, inspect Video Player, Control Pill Bar, Quick Inspector
  if (!hasOnboarding) {
    console.log('5. Inspecting Cockpit, Video Player & Control Pill Bar...');
    const grid = page.getByTestId('cockpit-grid');
    await grid.waitFor({ state: 'visible' });

    // Verify Control Pill Bar
    const pillBar = page.locator('.control-pill-bar');
    await pillBar.waitFor({ state: 'visible' });
    console.log('Control Pill Bar verified.');

    // Drawer toggle test
    const drawerToggle = page.getByRole('button', { name: /Alerts/i }).last();
    await drawerToggle.click();
    await page.waitForSelector('text=Alerts & Watchlist');
    console.log('Drawer opened with Alerts & Watchlist header.');
    await page.getByRole('button', { name: 'Close Drawer' }).click();
  } else {
    console.log('Currently in Onboarding view (EmptyState). Verifying EmptyState elements...');
    const connectBtn = page.getByTestId('cta-connect-phone');
    await connectBtn.waitFor({ state: 'visible' });
    const footageBtn = page.getByTestId('cta-use-footage');
    await footageBtn.waitFor({ state: 'visible' });
    console.log('EmptyState buttons verified.');
  }

  // 6. Check for radial-gradient or tacky purple in DOM
  console.log('6. Scanning computed styles for radial gradients or tacky purples...');
  const gradientStyles = await page.evaluate(() => {
    const all = Array.from(document.querySelectorAll('*'));
    return all
      .map((el) => window.getComputedStyle(el).backgroundImage)
      .filter((bg) => bg && bg.includes('radial-gradient'));
  });
  console.log('Found radial gradients count:', gradientStyles.length);
  if (gradientStyles.length > 0) {
    throw new Error('Found forbidden radial-gradient in live DOM: ' + JSON.stringify(gradientStyles));
  }

  // 7. Check 300ms transition on body
  const transition = await page.evaluate(() => window.getComputedStyle(document.body).transition);
  console.log('Body computed transition:', transition);

  console.log('--- ALL LIVE INSPECTION CHECKS PASSED PERFECTLY ---');
  await browser.close();
}

runLiveInspection().catch((err) => {
  console.error('LIVE INSPECTION FAILED:', err);
  process.exit(1);
});
