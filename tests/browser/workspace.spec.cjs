const { test, expect, language, submit } = require('./fixtures.cjs');

for (const lang of ['zh-Hant', 'en']) {
  test(`${lang}: native fallback without JavaScript`, async ({ browser, appURL }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    try {
      await context.route('**/*', route => new URL(route.request().url()).origin === appURL
        ? route.continue() : route.abort());
      const page = await context.newPage();
      await language(page, appURL, lang);
      await page.goto(appURL + '/projects/1?notes_size=10');
      await expect(page.locator('.note-card')).toHaveCount(10);
      await page.locator('[data-note-page]').first().click();
      await expect(page.locator('#project-notes')).toHaveAttribute('data-notes-page', '2');
      await page.locator('#important-links .add-form > summary').click();
      const form = page.locator('#important-links .add-form form');
      await form.locator('[name="title"]').fill('Native retry');
      await form.locator('[name="url"]').fill('https://fixture@example.invalid/');
      await submit(form);
      await expect(form.locator('[name="title"]')).toHaveValue('Native retry');
      await expect(form.locator('[name="url"]')).toHaveAttribute('aria-invalid', 'true');
      await form.locator('[name="url"]').fill('https://example.invalid/native');
      await submit(form);
      await expect(page.locator('.url-entry')).toHaveCount(2);
    } finally { await context.close(); }
  });

  test(`${lang}: native project errors, retry and real language switch`, async ({ page, appURL }) => {
    await language(page, appURL, lang);
    await page.goto(appURL + '/projects/new');
    const form = page.locator('#project-editor');
    await form.locator('[name="name"]').fill('x'.repeat(201));
    await form.locator('[name="description"]').fill('Retained description / 保留說明');
    const failed = page.waitForResponse(r => r.url().endsWith('/projects/new') && r.request().method() === 'POST');
    await submit(form);
    expect((await failed).status()).toBe(400);
    await expect(page.locator('.form-feedback')).toBeFocused();
    await expect(form.locator('[name="name"]')).toHaveAttribute('aria-invalid', 'true');
    await expect(form.locator('[name="description"]')).toHaveValue('Retained description / 保留說明');
    await expect(page.locator('.form-feedback')).toContainText(lang === 'en' ? 'Check your input' : '請檢查輸入資料');
    await form.locator('[name="name"]').fill('Created in browser');
    await form.locator('#project-owner').fill('Fixture team');
    await form.locator('#project-owner').press('Enter');
    await form.locator('#project-tags').fill('Browser');
    await form.locator('#project-tags').press('Enter');
    await submit(form);
    await expect(page).toHaveURL(/\/projects\/2/);
    await expect(page.locator('h1')).toHaveText('Created in browser');
    await expect(page.locator('.owner-badge')).toHaveText('Fixture team');
    await page.locator(`.language-switch button[value="${lang === 'en' ? 'zh-Hant' : 'en'}"]`).click();
    await expect(page.locator('html')).toHaveAttribute('lang', lang === 'en' ? 'zh-Hant' : 'en');
    await expect(page.locator('h1')).toHaveText('Created in browser');
  });

  test(`${lang}: content error retry, editing and keyboard cancel`, async ({ page, appURL }) => {
    await language(page, appURL, lang);
    await page.goto(appURL + '/projects/1');
    const section = page.locator('#important-links');
    await section.locator('.add-form > summary').click();
    let form = section.locator('.add-form form');
    await form.locator('[name="title"]').fill('Retained URL title');
    await form.locator('[name="url"]').fill('https://fixture@example.invalid/');
    const failed = page.waitForResponse(r => r.url().endsWith('/projects/1/urls') && r.request().method() === 'POST');
    await submit(form);
    expect((await failed).status()).toBe(400);
    await expect(form.locator('[name="title"]')).toHaveValue('Retained URL title');
    await expect(page.locator('.form-feedback')).toBeFocused();
    await expect(form.locator('[name="url"]')).toHaveAttribute('aria-invalid', 'true');
    await form.locator('[name="url"]').fill('https://example.invalid/retry');
    await submit(form);
    await expect(section.locator('.url-entry')).toHaveCount(2);
    const entry = section.locator('.url-entry').filter({ hasText: 'Retained URL title' });
    await entry.locator('.item-actions > summary').click();
    form = entry.locator('form[data-content-form]');
    await form.locator('[name="title"]').fill('Unsaved edit');
    await form.locator('[name="title"]').press('Escape');
    await expect(page.locator('#content-discard-dialog')).toBeVisible();
    await page.locator('[data-keep-content]').click();
    await expect(form.locator('[name="title"]')).toHaveValue('Unsaved edit');
    await form.locator('[name="title"]').fill('Updated URL title');
    await submit(form);
    await expect(section.locator('.url-name')).toContainText(['Updated URL title', 'Fixture URL']);
    await expect(section.locator('.url-entry')).toHaveCount(2);
  });

  test(`${lang}: two views, 10/20/50 paging, network fallback and draft protection`, async ({ page, appURL }) => {
    await language(page, appURL, lang);
    await page.goto(appURL + '/projects/1');
    const notes = page.locator('#project-notes');
    await page.locator('[data-detail-view="list"]').click();
    await expect(page.locator('#project-content')).toHaveAttribute('data-view', 'list');
    for (const size of [10, 50, 20]) {
      await notes.locator('[name="notes_size"]').selectOption(String(size));
      await submit(notes.locator('[data-note-page-size]'));
      await expect(notes.locator('.note-card')).toHaveCount(size);
    }
    await page.locator('[data-detail-view="cards"]').click();
    await expect(page.locator('#project-content')).toHaveAttribute('data-view', 'cards');
    await notes.locator('.add-form > summary').click();
    const draft = notes.locator('.add-form [name="title"]');
    await draft.fill('Keep this draft');
    await notes.locator('[data-note-page]').first().click();
    await expect(page.locator('#draft-leave-dialog')).toBeVisible();
    await page.locator('[data-stay-page]').click();
    await expect(draft).toHaveValue('Keep this draft');
    await notes.locator('[data-note-page]').first().click();
    await page.locator('[data-leave-page]').click();
    await expect(notes).toHaveAttribute('data-notes-page', '2');
    await page.route('**/projects/1?*', route => route.request().headers()['x-projmemo-fragment']
      ? route.abort('failed') : route.continue());
    await notes.locator('[data-note-page]').first().click();
    await expect(notes.locator('.note-load-feedback')).toBeVisible();
    await expect(notes).toHaveAttribute('data-notes-page', '2');
    await page.unroute('**/projects/1?*');
    await notes.locator('[data-note-page]').first().click();
    await expect(notes).toHaveAttribute('data-notes-page', '1');
    await page.locator('#important-links .add-form > summary').click();
    await page.locator('#important-links .add-form [name="title"]').fill('Language draft');
    await page.locator('.language-switch button:not(.active)').click();
    await expect(page.locator('#draft-leave-dialog')).toBeVisible();
    await page.locator('[data-stay-page]').click();
    await expect(page.locator('html')).toHaveAttribute('lang', lang);
    await expect(page.locator('#important-links .add-form [name="title"]')).toHaveValue('Language draft');
  });

  test(`${lang}: real backup download, invalid upload and successful restore`, async ({ page, appURL }) => {
    await language(page, appURL, lang);
    await page.goto(appURL + '/settings/backup');
    const downloadPromise = page.waitForEvent('download');
    await page.locator('a[href="/settings/backup/download"]').click();
    const download = await downloadPromise;
    const chunks = [];
    for await (const chunk of await download.createReadStream()) chunks.push(chunk);
    const backup = Buffer.concat(chunks);
    expect(backup.subarray(0, 16).toString()).toBe('SQLite format 3\0');
    page.on('dialog', dialog => dialog.accept());
    await page.locator('#backup-file').setInputFiles({ name: 'invalid.sqlite3', mimeType: 'application/octet-stream', buffer: Buffer.from('not SQLite') });
    await submit(page.locator('.backup-restore-form'));
    await expect(page.locator('.backup-error')).toBeVisible();
    await page.goto(appURL + '/projects/1');
    await expect(page.locator('h1')).toContainText('Browser fixture');
    await page.goto(appURL + '/projects/new');
    await page.locator('[name="name"]').fill('Removed by restore');
    await submit(page.locator('#project-editor'));
    await expect(page).toHaveURL(/\/projects\/2/);
    await page.goto(appURL + '/settings/backup');
    await page.locator('#backup-file').setInputFiles({ name: 'fixture.sqlite3', mimeType: 'application/vnd.sqlite3', buffer: backup });
    await submit(page.locator('.backup-restore-form'));
    await expect(page.locator('#restore-preview')).toBeVisible();
    await page.locator('#restore-preview [name="acknowledged"]').check();
    await page.locator('#restore-confirmation').fill('RESTORE');
    await submit(page.locator('#restore-preview .backup-confirm-form'));
    await expect(page.locator('.backup-success')).toBeVisible();
    await page.goto(appURL + '/');
    await expect(page.locator('main')).not.toContainText('Removed by restore');
    await expect(page.locator('main')).toContainText('Browser fixture');
  });

  test(`${lang}: encrypted fixture account, reveal, lock and safe unlock error`, async ({ page, appURL }) => {
    await language(page, appURL, lang);
    await page.goto(appURL + '/settings/vault');
    const master = 'R08 synthetic master phrase only';
    const secret = 'R08-fixture-secret-not-real';
    const setup = page.locator('form[action="/settings/vault/setup"]');
    await setup.locator('[name="master_password"]').fill(master);
    await setup.locator('[name="confirm_password"]').fill(master);
    await submit(setup);
    await expect(page.locator('[data-vault-state]')).toHaveAttribute('data-vault-state', 'unlocked');
    await page.goto(appURL + '/projects/1');
    await page.locator('#access-accounts .add-form > summary').click();
    const form = page.locator('#access-accounts .add-form form');
    await form.locator('[name="label"]').fill('Synthetic database account');
    await form.locator('[name="endpoint"]').fill('host.example.invalid:5432');
    await form.locator('[name="username"]').fill('fixture-user');
    await form.locator('[name="secret_value"]').fill(secret);
    await submit(form);
    await expect(page.locator('[data-secret-output]')).not.toContainText(secret);
    await page.locator('[data-reveal-url]').click();
    await expect(page.locator('[data-secret-output]')).toHaveText(secret);
    const exported = await page.context().request.get(appURL + '/projects/1/export.md');
    expect((await exported.text()).includes(secret)).toBe(false);
    expect(await page.evaluate(() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)]))).not.toContain(secret);
    await page.locator('#access-accounts form[action="/settings/vault/lock"] button').click();
    await expect(page.locator('[data-reveal-url]')).toHaveCount(0);
    await page.goto(appURL + '/settings/vault');
    const unlock = page.locator('form[action="/settings/vault/unlock"]');
    await unlock.locator('[name="master_password"]').fill('Wrong synthetic master phrase');
    await submit(unlock);
    await expect(unlock.locator('[name="master_password"]')).toHaveValue('');
    await expect(page.locator('body')).not.toContainText('Wrong synthetic master phrase');
    await unlock.locator('[name="master_password"]').fill(master);
    await submit(unlock);
    await expect(page.locator('[data-vault-state]')).toHaveAttribute('data-vault-state', 'unlocked');
  });
}
