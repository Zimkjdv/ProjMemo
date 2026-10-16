const { test, expect, language, submit } = require('./fixtures.cjs');

for (const lang of ['zh-Hant', 'en']) {
  test(`${lang}: combined content filters, views, preferences and progress`, async ({ page, appURL }) => {
    await language(page, appURL, lang);
    await page.goto(appURL + '/projects/1/edit');
    const editor = page.locator('#project-editor');
    await editor.locator('#project-owner').fill('Fixture team');
    await editor.locator('#project-owner').press('Enter');
    await editor.locator('#project-tags').fill('R10');
    await editor.locator('#project-tags').press('Enter');
    await submit(editor);
    await page.goto(appURL + '/projects/1');
    await page.locator('#handover .add-form > summary').click();
    const checklist = page.locator('#handover .add-form form');
    await checklist.locator('[name="title"]').fill('Pending browser transfer');
    await submit(checklist);
    await page.goto(appURL + '/');
    let form = page.locator('.search-filter-bar');
    await form.locator('[name="q"]').fill('備註 3');
    await form.locator('[name="search_scope"]').selectOption('all');
    await form.locator('.advanced-search > summary').click();
    await form.locator('[name="owner"]').fill('Fixture team');
    await form.locator('[name="tag"]').fill('R10');
    await form.locator('[name="handover"]').selectOption('pending');
    await form.locator('button[type="submit"]').click();
    await expect(page.locator('.project-card')).toHaveCount(1);
    await expect(page.locator('.handover-progress progress')).toHaveAttribute('max', '1');
    await page.locator('.view-switch a').last().click();
    await expect(page.locator('.project-list-row')).toHaveCount(1);
    await expect(page).toHaveURL(/search_scope=all/);
    await expect(page).toHaveURL(/owner=Fixture\+team/);
    // A rendered table precedes deferred preference persistence. Verify the
    // actual stored view before starting a new navigation that could abort it.
    await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('projmemo.listPreferences.v1')).view)).toBe('list');
    // Bare home restores new applied filters; explicit blanks/reset remain authoritative.
    await page.goto(appURL + '/');
    await expect(page.locator('[name="tag"]')).toHaveValue('R10');
    await expect(page.locator('.project-list-row')).toHaveCount(1);
    for (const width of [1280, 1440, 1920]) {
      await page.setViewportSize({ width, height: 1000 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await expect(page.locator('.search-filter-bar')).toHaveCSS('display', 'block');
      const outer = await page.locator('.search-filter-bar').boundingBox();
      const advanced = await page.locator('.advanced-search').boundingBox();
      expect(advanced.width).toBeGreaterThan(outer.width - 50);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.keyboard.press('Control+Home');
    await page.screenshot({ path: test.info().outputPath('search-filters.png'), fullPage: true });
    await page.locator('.project-list-progress > a').click();
    await expect(page).toHaveURL(/checklist=pending/);
    await expect(page.locator('#handover .checklist-item')).toHaveCount(1);
    await page.locator('#handover .check-button').click();
    await expect(page).toHaveURL(/checklist=pending/);
    await expect(page.locator('#handover .checklist-item')).toHaveCount(0);
    await expect(page.locator('#handover progress')).toHaveAttribute('value', '1');
    await page.goto(appURL + '/?owner=&tag=&handover=&search_scope=basic&q=');
    await expect(page.locator('[name="q"]')).toHaveValue('');
    await expect(page.locator('[name="tag"]')).toHaveValue('');
    await page.locator('[data-reset-list-preferences]').click();
    await expect(page).toHaveURL(/view=cards&page_size=10&page=1&q=&status=$/);
    await page.waitForLoadState('load');
    await expect(page.locator('.project-card')).toHaveCount(1);
  });

  test(`${lang}: pending handover native fallback and note paging keep full counts`, async ({ browser, appURL }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    try {
      await context.route('**/*', route => new URL(route.request().url()).origin === appURL ? route.continue() : route.abort());
      const page = await context.newPage();
      await language(page, appURL, lang);
      await page.goto(appURL + '/projects/1');
      await page.locator('#handover .add-form > summary').click();
      const form = page.locator('#handover .add-form form');
      await form.locator('[name="title"]').fill('Native transfer');
      await submit(form);
      await page.locator('.checklist-filters a').last().click();
      await expect(page).toHaveURL(/checklist=pending/);
      const pager = page.locator('[data-note-page-size]').first();
      await pager.locator('[name="notes_size"]').selectOption('10');
      await submit(pager);
      await expect(page).toHaveURL(/checklist=pending/);
      await expect(page.locator('.note-card')).toHaveCount(10);
      await page.locator('#handover .check-button').click();
      await expect(page.locator('#handover .checklist-item')).toHaveCount(0);
      await expect(page.locator('#handover .section-count')).toHaveText('1');
      await page.locator('.checklist-filters a').first().click();
      await expect(page.locator('#handover .checklist-item')).toHaveCount(1);
    } finally { await context.close(); }
  });
}
