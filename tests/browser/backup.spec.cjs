const { test, expect, language, submit } = require('./fixtures.cjs');

async function downloadBackup(page) {
  const pending = page.waitForEvent('download');
  await page.locator('a[href="/settings/backup/download"]').click();
  const chunks = [];
  for await (const chunk of await (await pending).createReadStream()) chunks.push(chunk);
  return Buffer.concat(chunks);
}

for (const lang of ['zh-Hant', 'en']) {
  test(`${lang}: preview cancellation is native, safe and does not persist tokens`, async ({ page, appURL }, testInfo) => {
    await language(page, appURL, lang);
    await page.goto(appURL + '/settings/backup');
    const backup = await downloadBackup(page);
    await page.locator('#backup-file').setInputFiles({ name: 'fixture.sqlite3', mimeType: 'application/vnd.sqlite3', buffer: backup });
    await submit(page.locator('.backup-restore-form'));
    await expect(page.locator('#restore-preview')).toBeVisible();
    await expect(page.locator('#restore-preview tbody tr')).toHaveCount(14);
    await expect(page.locator('#restore-preview .checkbox-row')).toHaveCSS('display', 'flex');
    await expect(page.locator('#restore-preview .checkbox-row input')).toHaveCSS('height', '18px');
    const token = await page.locator('#restore-preview [name="preview_token"]').first().inputValue();
    expect(page.url()).not.toContain(token);
    expect(await page.evaluate(() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)]))).not.toContain(token);
    for (const width of [1280, 1440, 1920]) {
      await page.setViewportSize({ width, height: 1000 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(await page.locator('#restore-preview').evaluate(node => node.getBoundingClientRect().right <= innerWidth)).toBe(true);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({ path: testInfo.outputPath('backup-preview.png'), fullPage: true });
    await submit(page.locator('#restore-preview .backup-cancel-form'));
    await expect(page).toHaveURL(appURL + '/settings/backup');
    await expect(page.locator('#restore-preview')).toHaveCount(0);
    await expect(page.locator('.backup-history-row')).toHaveCount(0);
    await page.goto(appURL + '/projects/1');
    await expect(page.locator('h1')).toContainText('Browser fixture');
  });

  test(`${lang}: restore confirmation works with JavaScript disabled`, async ({ browser, appURL }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    try {
      await page.route('**/*', route => new URL(route.request().url()).origin === appURL ? route.continue() : route.abort());
      await language(page, appURL, lang);
      await page.goto(appURL + '/settings/backup');
      const backup = await downloadBackup(page);
      await page.locator('#backup-file').setInputFiles({ name: 'fixture.sqlite3', mimeType: 'application/vnd.sqlite3', buffer: backup });
      await submit(page.locator('.backup-restore-form'));
      await expect(page.locator('#restore-preview')).toBeVisible();
      await page.locator('#restore-preview [name="acknowledged"]').check();
      await page.locator('#restore-confirmation').fill('RESTORE');
      await submit(page.locator('#restore-preview .backup-confirm-form'));
      await expect(page.locator('.backup-success')).toBeVisible();
      await expect(page.locator('.backup-history-row')).toHaveCount(1);
    } finally {
      await context.close();
    }
  });

  test(`${lang}: changing language from preview returns to a safe GET page`, async ({ page, appURL }) => {
    await language(page, appURL, lang);
    await page.goto(appURL + '/settings/backup');
    const backup = await downloadBackup(page);
    await page.locator('#backup-file').setInputFiles({ name: 'fixture.sqlite3', mimeType: 'application/vnd.sqlite3', buffer: backup });
    await submit(page.locator('.backup-restore-form'));
    await expect(page.locator('#restore-preview')).toBeVisible();
    await page.locator('.language-switch button:not(.active)').click();
    await expect(page).toHaveURL(appURL + '/settings/backup');
    await expect(page.locator('#backup-title')).toBeVisible();
    await expect(page.locator('#restore-preview')).toHaveCount(0);
  });

  test(`${lang}: retention settings and preview never delete without final confirmation`, async ({ page, appURL }, testInfo) => {
    await language(page, appURL, lang);
    await page.goto(appURL + '/settings/backup');
    const backup = await downloadBackup(page);
    const csrf = await page.locator('meta[name="csrf-token"]').getAttribute('content');
    // Seed only this private fixture's real, validated recovery snapshots.
    for (let index = 0; index < 3; index++) {
      const response = await page.context().request.post(appURL + '/settings/backup/restore', {
        headers: { 'X-CSRF-Token': csrf },
        multipart: { backup_file: { name: 'fixture.sqlite3', mimeType: 'application/vnd.sqlite3', buffer: backup } },
        maxRedirects: 0,
      });
      expect(response.status()).toBe(303);
    }
    await page.goto(appURL + '/settings/backup');
    await expect(page.locator('.backup-history-row')).toHaveCount(3);
    await page.locator('.backup-retention-details > summary').click();
    await page.locator('#retention-mode').selectOption('custom');
    await page.locator('#retention-count').fill('1');
    await page.locator('#retention-days').fill('0');
    await submit(page.locator('.backup-policy-form'));
    await expect(page.locator('.backup-history-row')).toHaveCount(3);
    const previewForm = page.locator('form[action="/settings/backup/cleanup/preview"]');
    await submit(previewForm);
    await expect(page.locator('.backup-candidate-list li')).toHaveCount(2);
    await expect(page.locator('.backup-history-row')).toHaveCount(3);
    await expect(page.locator('.backup-policy-form')).toHaveCSS('display', 'grid');
    await expect(page.locator('.backup-cleanup-preview .checkbox-row input')).toHaveCSS('height', '18px');
    await page.screenshot({ path: testInfo.outputPath('backup-retention.png'), fullPage: true });
    await submit(page.locator('#cleanup-preview .backup-cancel-form'));
    await expect(page.locator('.backup-history-row')).toHaveCount(3);
    await page.locator('.backup-retention-details > summary').click();
    await submit(previewForm);
    await page.locator('#cleanup-preview [name="acknowledged"]').check();
    await page.locator('#cleanup-confirmation').fill('DELETE');
    await submit(page.locator('#cleanup-preview .backup-confirm-form'));
    await expect(page.locator('.backup-retention .backup-success')).toBeVisible();
    await expect(page.locator('.backup-history-row')).toHaveCount(1);
    await expect(page.locator('#retention-count')).toHaveValue('1');
  });
}
