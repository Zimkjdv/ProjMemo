const { test, expect, language, submit } = require('./fixtures.cjs');

async function drop(page, files) {
  await page.evaluate(entries => {
    const transfer = new DataTransfer();
    for (const entry of entries) {
      const bytes = entry.base64 ? Uint8Array.from(atob(entry.base64), char => char.charCodeAt(0)) : new Uint8Array(entry.size || 0);
      transfer.items.add(new File([bytes], entry.name, { type: 'application/vnd.sqlite3' }));
    }
    document.querySelector('[data-backup-dropzone]').dispatchEvent(new DragEvent('drop', { dataTransfer: transfer, bubbles: true, cancelable: true }));
  }, files);
}

for (const locale of ['zh-Hant', 'en']) {
  test(`${locale}: desktop backup dashboard, real activity, safe drop and advanced settings`, async ({ page, appURL }) => {
    await language(page, appURL, locale); await page.goto(appURL + '/settings/backup');
    const preview = page.locator('[data-backup-preview-button]');
    await expect(preview).toBeDisabled();
    await expect(page.locator('[data-backup-file-status]')).toBeHidden();
    await expect(page.locator('[data-backup-file-status]')).toBeEmpty();
    await expect(page.locator('.backup-download-footer > span')).toHaveCount(0);
    await expect(page.locator('.backup-summary-help')).toHaveCount(0);
    await expect(page.locator('[data-backup-download-time]')).toHaveText(locale === 'en' ? 'No record yet' : '尚無紀錄');
    await expect(page.locator('.backup-steps [aria-current="step"]')).toContainText('1');
    await expect(page.locator('.backup-retention-details')).not.toHaveAttribute('open');
    for (const width of [1280, 1440, 1920]) {
      await page.setViewportSize({ width, height: 1000 });
      const layout = await page.locator('.backup-grid').evaluate(grid => {
        const cards = [...grid.children].map(card => card.getBoundingClientRect());
        const left = grid.querySelector('.backup-download-footer .button').getBoundingClientRect();
        const right = grid.querySelector('[data-backup-preview-button]').getBoundingClientRect();
        return { heights: cards.map(card => card.height), buttons: [left.bottom, right.bottom], overflow: document.documentElement.scrollWidth > innerWidth };
      });
      expect(Math.abs(layout.heights[0] - layout.heights[1])).toBeLessThan(1);
      expect(Math.abs(layout.buttons[0] - layout.buttons[1])).toBeLessThan(2);
      expect(layout.overflow).toBe(false);
      const smallestText = await page.locator('.backup-page').evaluate(root => Math.min(...[...root.querySelectorAll('*')]
        .filter(element => element.getClientRects().length && [...element.childNodes].some(child => child.nodeType === 3 && child.textContent.trim()))
        .map(element => parseFloat(getComputedStyle(element).fontSize))));
      expect(smallestText).toBeGreaterThanOrEqual(13);
      await page.screenshot({ path: `data/backup-dashboard-${locale}-${width}.png`, fullPage: true });
    }
    const result = await page.request.get(appURL + '/settings/backup/download');
    expect(result.ok()).toBe(true); const buffer = await result.body();
    await page.reload();
    await expect(page.locator('[data-backup-download-time] time')).toHaveAttribute('datetime', /T.*\+00:00$/);
    let uploads = 0;
    page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/backup/preview')) uploads++; });
    const chooser = page.waitForEvent('filechooser');
    await page.locator('[data-backup-pick-label]').click();
    await (await chooser).setFiles({ name: 'picker.sqlite3', mimeType: 'application/vnd.sqlite3', buffer });
    await expect(preview).toBeEnabled();
    await expect(page.locator('[data-backup-file-status]')).toBeVisible();
    await page.locator('#backup-file').setInputFiles([]);
    await expect(preview).toBeDisabled();
    await expect(page.locator('[data-backup-file-status]')).toBeEmpty();
    await expect(page.locator('[data-backup-file-status]')).toBeHidden();
    await drop(page, [{ name: 'empty.sqlite3', size: 0 }]);
    await expect(preview).toBeDisabled(); await expect(page.locator('[data-backup-file-status]')).toHaveAttribute('data-state', 'error');
    await expect(page.locator('[data-backup-file-status]')).toBeVisible();
    await drop(page, [{ name: 'one.db', size: 1 }, { name: 'two.db', size: 1 }]);
    await expect(preview).toBeDisabled();
    await drop(page, [{ name: '<img>.sqlite3', base64: buffer.toString('base64') }]);
    await expect(preview).toBeEnabled();
    await expect(page.locator('[data-backup-file-status]')).toContainText('<img>.sqlite3');
    await expect(page.locator('[data-backup-file-status] img')).toHaveCount(0);
    expect(uploads).toBe(0); // Dropping a backup does not upload it automatically.
    await preview.click();
    await expect(page.locator('#restore-preview')).toBeVisible();
    await expect(page.locator('#restore-preview .backup-steps [aria-current="step"]')).toContainText('2');
    await expect(page.locator('.backup-restore-form')).toHaveCount(0);
    await submit(page.locator('#restore-preview .backup-cancel-form'));
    await page.locator('.backup-retention-details > summary').click();
    await expect(page.locator('[data-retention-custom]')).toBeHidden();
    await page.locator('#retention-mode').selectOption('custom');
    await page.locator('#retention-count').fill('7');
    await page.locator('#retention-mode').selectOption('all');
    await expect(page.locator('#retention-count')).toBeDisabled();
    await page.locator('#retention-mode').selectOption('custom');
    await expect(page.locator('#retention-count')).toHaveValue('7');
    await submit(page.locator('.backup-policy-form'));
    await expect(page.locator('#retention-count')).toHaveValue('7');
    await expect(page.locator('.backup-history-row')).toHaveCount(0);
  });

  test(`${locale}: recovery-table action previews before any replacement`, async ({ page, appURL }) => {
    await language(page, appURL, locale); await page.goto(appURL + '/settings/backup');
    const buffer = await (await page.request.get(appURL + '/settings/backup/download')).body();
    const csrf = await page.locator('meta[name="csrf-token"]').getAttribute('content');
    const response = await page.request.post(appURL + '/settings/backup/restore', {
      headers: { 'X-CSRF-Token': csrf }, multipart: { backup_file: { name: 'fixture.sqlite3', mimeType: 'application/vnd.sqlite3', buffer } }, maxRedirects: 0 });
    expect(response.status()).toBe(303); await page.reload();
    await expect(page.locator('.backup-recovery-table tbody tr')).toHaveCount(1);
    await page.locator('.backup-recovery-actions form button').click();
    await expect(page.locator('#restore-preview')).toBeVisible();
    await expect(page.locator('.backup-history-row')).toHaveCount(1);
    await expect(page.locator('#restore-confirmation')).toBeEmpty();
    await expect(page.locator('#restore-preview [name="acknowledged"]')).not.toBeChecked();
  });

  test.describe(`${locale} native advanced settings`, () => {
    test.use({ javaScriptEnabled: false });
    test('native picker and collapsible retention stay usable', async ({ page, appURL }) => {
      await language(page, appURL, locale); await page.goto(appURL + '/settings/backup');
      await expect(page.locator('[data-backup-preview-button]')).toBeEnabled();
      await expect(page.locator('[data-backup-file-status]')).toBeHidden();
      await expect(page.locator('[data-backup-file-status]')).toBeEmpty();
      await page.locator('.backup-retention-details > summary').click();
      await expect(page.locator('[data-retention-custom]')).toBeVisible();
      await page.locator('#retention-mode').selectOption('custom');
      await page.locator('#retention-count').fill('4');
      await submit(page.locator('.backup-policy-form'));
      await expect(page.locator('#retention-count')).toHaveValue('4');
      await expect(page.locator('.backup-retention-details')).toHaveAttribute('open');
    });
  });
}
