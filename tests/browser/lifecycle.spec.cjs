const { test, expect, language, submit } = require('./fixtures.cjs');

for (const lang of ['zh-Hant', 'en']) {
  test(`${lang}: archive, trash, restore and permanent deletion of disposable project`, async ({ page, appURL }) => {
    await language(page, appURL, lang);
    await page.goto(appURL + '/projects/1');
    await page.locator('.project-actions a[href$="/manage"]').click();
    await expect(page.locator('.lifecycle-counts dd')).toHaveText(['1', '55', '0', '0', '0']);
    await page.screenshot({ path: test.info().outputPath('manage-project.png'), fullPage: true });
    const name = 'Browser fixture / 瀏覽器範例';
    const change = async action => {
      const form = page.locator(`form[action="/projects/1/lifecycle/${action}"]`);
      await form.locator('..').locator('summary').click();
      await form.locator('[name="confirmation_name"]').fill(name);
      await form.locator('[name="confirmed"]').check();
      await submit(form);
      await expect(page.locator('.operation-success')).toBeVisible();
    };
    await change('archive');
    await page.locator('.lifecycle-links a').first().click();
    await expect(page.locator('.collection-tabs [aria-current="page"]')).toHaveAttribute('href', /collection=archived/);
    await page.locator('.project-card').click();
    await expect(page.locator('.project-title-row .lifecycle-badge')).toBeVisible();
    await page.locator('.project-actions a[href$="/manage"]').click();
    await change('trash');
    await expect(page.locator('a[href="/projects/1"]')).toHaveCount(0);
    await page.locator('.lifecycle-links a').first().click();
    await expect(page.locator('.collection-tabs [aria-current="page"]')).toHaveAttribute('href', /collection=trash/);
    await page.locator('.project-card').click();
    await change('restore');
    await expect(page.locator('form[action$="/unarchive"]')).toHaveCount(1);
    await change('unarchive');
    await change('trash');
    // A wrong name is a recoverable native error, never a deletion.
    const purge = page.locator('form[action$="/purge"]');
    await purge.locator('..').locator('summary').click();
    await page.screenshot({ path: test.info().outputPath('trash-confirmation.png'), fullPage: true });
    await purge.locator('[name="confirmation_name"]').fill('not the fixture name');
    await purge.locator('[name="confirmed"]').check();
    await submit(purge);
    await expect(page.locator('.form-feedback')).toBeFocused();
    await expect(purge.locator('[name="confirmation_name"]')).toHaveValue('');
    await expect(purge.locator('[name="confirmed"]')).not.toBeChecked();
    await purge.locator('[name="confirmation_name"]').fill(name);
    await purge.locator('[name="confirmed"]').check();
    await submit(purge);
    await expect(page).toHaveURL(/collection=trash/);
    await expect(page.locator('.project-card')).toHaveCount(0);
    await page.goto(appURL + '/settings/backup');
    await expect(page.locator('.backup-history-row')).toHaveCount(1);
    await expect(page.locator('.backup-history-row')).toContainText('projmemo-pre-delete-');
  });

  test(`${lang}: lifecycle confirmation is usable without JavaScript`, async ({ browser, appURL }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    try {
      await context.route('**/*', route => new URL(route.request().url()).origin === appURL ? route.continue() : route.abort());
      const page = await context.newPage();
      await language(page, appURL, lang);
      await page.goto(appURL + '/projects/1/manage');
      const form = page.locator('form[action$="/archive"]');
      await form.locator('..').locator('summary').click();
      await form.locator('[name="confirmation_name"]').fill('Browser fixture / 瀏覽器範例');
      await form.locator('[name="confirmed"]').check();
      await submit(form);
      await expect(page.locator('form[action$="/unarchive"]')).toHaveCount(1);
    } finally { await context.close(); }
  });
}
