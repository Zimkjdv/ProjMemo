const fs = require('node:fs');
const { test, expect, language } = require('./fixtures.cjs');

for (const lang of ['zh-Hant', 'en']) {
  test(`${lang}: templates, safe preview, stale results and paged editors`, async ({ page, appURL }) => {
    await language(page, appURL, lang);
    await page.goto(appURL + '/projects/1?notes_size=10');
    await page.locator('#project-notes > .add-form > summary').click();
    let editor = page.locator('#project-notes > .add-form [data-markdown-editor]');
    const draft = '# 原文 / Original\n\n**Bold**\n\n<script>parent.injected=true</script>\n\n```mermaid\ngraph TD; A-->B\n```';
    await editor.locator('textarea').fill(draft);
    await editor.locator('select').selectOption('deployment');
    page.once('dialog', dialog => dialog.dismiss());
    await editor.locator('[data-apply-template]').click();
    await expect(editor.locator('textarea')).toHaveValue(draft);
    await editor.locator('[data-markdown-preview]').click();
    await expect(editor.locator('iframe')).toBeVisible();
    await expect(editor.frameLocator('iframe').locator('strong')).toHaveText('Bold');
    await expect(editor.frameLocator('iframe').locator('script, svg, img, a[href]')).toHaveCount(0);
    expect(await page.evaluate(() => window.injected)).toBeUndefined();
    await expect(editor.frameLocator('iframe').locator('code')).toContainText('graph TD');
    page.once('dialog', dialog => dialog.accept());
    await editor.locator('[data-apply-template]').click();
    await expect(editor.locator('textarea')).toHaveValue(lang === 'en' ? /Pre-deployment/ : /部署前檢查/);
    await expect(editor.locator('iframe')).toBeHidden();
    await page.route('**/editor/preview', async route => {
      await new Promise(resolve => setTimeout(resolve, 300));
      await route.fulfill({ json: { document: '<p>STALE RESULT</p>' } }).catch(() => {});
    });
    await editor.locator('[data-markdown-preview]').click();
    await editor.locator('textarea').fill('Newer draft');
    await page.waitForTimeout(400);
    await expect(editor.locator('iframe')).toBeHidden();
    await expect(editor.locator('textarea')).toHaveValue('Newer draft');
    await page.unroute('**/editor/preview');
    await page.route('**/editor/preview', route => route.fulfill({ status: 503, body: 'unavailable' }));
    await editor.locator('[data-markdown-preview]').click();
    await expect(editor.locator('[data-preview-status]')).toContainText(lang === 'en' ? 'failed' : '失敗');
    await expect(editor.locator('textarea')).toHaveValue('Newer draft');
    await page.unroute('**/editor/preview');
    await editor.locator('textarea').fill('');
    await page.locator('[data-note-page]').first().click();
    await expect(page.locator('#project-notes')).toHaveAttribute('data-notes-page', '2');
    await page.locator('#project-notes > .add-form > summary').click();
    editor = page.locator('#project-notes > .add-form [data-markdown-editor]');
    await editor.locator('select').selectOption('issue');
    await editor.locator('[data-apply-template]').click();
    await expect(editor.locator('textarea')).toHaveValue(lang === 'en' ? /Workaround/ : /替代方案/);
    await editor.locator('[data-markdown-preview]').click();
    await expect(editor.locator('iframe')).toBeVisible();
    expect(await page.evaluate(() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])))
      .not.toContain('Newer draft');
    // Screenshot contains fake data only and stays under ignored test output.
    await page.screenshot({ path: `data/r12-editor-${lang}.png`, fullPage: false });
  });

  test(`${lang}: configured download keeps independent document language`, async ({ page, appURL }) => {
    await language(page, appURL, lang);
    await page.goto(appURL + '/projects/1/export');
    await page.locator('[name="document_language"]').selectOption(lang === 'en' ? 'zh-Hant' : 'en');
    for (const box of await page.locator('[name="sections"]').all()) await box.uncheck();
    await page.locator('[name="sections"][value="description"]').check();
    const pending = page.waitForEvent('download');
    await page.locator('.export-options button[type="submit"]').click();
    const download = await pending;
    const content = fs.readFileSync(await download.path(), 'utf8');
    expect(content).toContain(lang === 'en' ? '## 專案描述' : '## Project description');
    expect(content).not.toContain('Fixture note');
    expect(content).toContain('Browser fixture / 瀏覽器範例');
    await expect(page.locator('.export-options button[type="submit"]')).toBeEnabled();
    await page.screenshot({ path: `data/r12-export-${lang}.png` });
  });

  test(`${lang}: native preview and templates do not save notes`, async ({ browser, appURL }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    try {
      const page = await context.newPage();
      await language(page, appURL, lang);
      await page.goto(appURL + '/editor?template=handover');
      await expect(page.locator('textarea')).toContainText(lang === 'en' ? 'Scope and contacts' : '範圍與窗口');
      const popup = context.waitForEvent('page');
      await page.locator('noscript button').click();
      const preview = await popup;
      await expect(preview.locator('h2').first()).toHaveText(lang === 'en' ? 'Scope and contacts' : '範圍與窗口');
      await expect(preview.locator('script, svg, img, a[href]')).toHaveCount(0);
      await preview.close();
      await page.goto(appURL + '/projects/1');
      await expect(page.locator('#project-notes')).toHaveAttribute('data-note-total', '55');
    } finally { await context.close(); }
  });
}
