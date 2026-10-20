// Optional real-browser traffic against the private Windows launcher fixture.
const assert = require('node:assert/strict');
const { chromium } = require('@playwright/test');

async function main() {
  const url = process.argv[2];
  assert.match(url || '', /^http:\/\/127\.0\.0\.1:[0-9]{1,5}$/);
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext();
    await context.route('**/*', route => new URL(route.request().url()).origin === url
      ? route.continue() : route.abort());
    const page = await context.newPage();
    page.setDefaultNavigationTimeout(5000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(url + '/');
    // Refuse to stress a user's ordinary server even if given the wrong URL.
    assert.match(await page.locator('body').innerText(), /Windows lifecycle synthetic fixture/);
    for (let cycle = 0; cycle < 6; cycle++) {
      const cancelled = page.goto(url + '/projects/1?detail_view=list').catch(error => {
        assert.match(error.message, /ERR_ABORTED|interrupted by another navigation/);
      });
      await page.goto(url + '/projects/1?detail_view=cards');
      await cancelled;
      assert.match(await page.locator('body').innerText(), /Synthetic note/);
    }
    await page.goto(url + '/settings/backup');
    await page.goto(url + '/settings/vault');
    await page.goto(url + '/');
    assert.deepEqual(errors, []);
    await context.close();
    console.log('Private Chromium navigation/cancellation passed.');
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
