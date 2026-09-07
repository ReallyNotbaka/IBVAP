import { chromium } from '@playwright/test';

async function main() {
  console.log('[Agentic Browser] Launching visible browser connected to http://localhost:8000...');
  const browser = await chromium.launch({
    headless: false,
    args: ['--start-maximized']
  });
  const context = await browser.newContext({ viewport: null });
  const page = await context.newPage();
  
  await page.goto('http://localhost:8000', { waitUntil: 'domcontentloaded' });
  console.log('[Agentic Browser] Successfully connected to http://localhost:8000. Session active.');

  // Keep browser alive until user closes the window
  await new Promise((resolve) => {
    browser.on('disconnected', resolve);
  });
}

main().catch(err => {
  console.error('[Agentic Browser Error]:', err);
});
