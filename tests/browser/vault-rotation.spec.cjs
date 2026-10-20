const { test, expect, language } = require('./fixtures.cjs');

const oldPassword = '  browser synthetic old master  ';
const newPassword = '  browser 新主密碼 phrase 2026  ';
const secret = 'R13 browser synthetic account secret';

for (const locale of ['zh-Hant', 'en']) {
  for (const native of [false, true]) {
    test(`${locale}: ${native ? 'native' : 'enhanced'} password change, retry and old-key recovery`, async ({ browser, appURL }) => {
      const context = await browser.newContext({ javaScriptEnabled: !native });
      let peer;
      try {
        const page = await context.newPage();
        await language(page, appURL, locale);
        await page.goto(appURL + '/settings/vault');
        const setup = page.locator('form[action="/settings/vault/setup"]');
        await setup.locator('[name="master_password"]').fill(oldPassword);
        await setup.locator('[name="confirm_password"]').fill(oldPassword);
        await setup.locator('button').click();
        await expect(page.locator('.vault-page')).toHaveAttribute('data-vault-state', 'unlocked');
        const csrf = await page.locator('meta[name="csrf-token"]').getAttribute('content');
        const added = await page.request.post(appURL + '/projects/1/accounts', { form: {
          label: 'R13 synthetic test account', secret_value: secret }, headers: { 'X-CSRF-Token': csrf }, maxRedirects: 0 });
        expect(added.status()).toBe(303);
        if (!native) {
          peer = await context.newPage();
          await peer.goto(appURL + '/projects/1');
          await expect(peer.locator('.secret-reveal')).toBeEnabled();
          await peer.locator('.secret-reveal').click();
          await expect(peer.locator('[data-secret-output]')).toHaveText(secret);
        }
        await page.locator('.vault-rotation-details > summary').click();
        const form = page.locator('form[action="/settings/vault/change-password"]');
        await form.locator('[name="current_master_password"]').fill('wrong synthetic master');
        await form.locator('[name="new_master_password"]').fill(newPassword);
        await form.locator('[name="confirm_new_password"]').fill(newPassword);
        await form.locator('[name="confirm_password_change"]').check();
        await form.locator('button').click();
        await expect(form.locator('[name="current_master_password"]')).toHaveValue('');
        await expect(form.locator('[name="new_master_password"]')).toHaveValue('');
        await expect(form.locator('[name="confirm_new_password"]')).toHaveValue('');
        await expect(form.locator('[name="confirm_password_change"]')).not.toBeChecked();
        await expect(page.locator('.form-feedback')).toContainText(locale === 'en' ? 'incorrect' : '錯誤');
        await form.locator('[name="current_master_password"]').fill(oldPassword);
        await form.locator('[name="new_master_password"]').fill(newPassword);
        await form.locator('[name="confirm_new_password"]').fill(newPassword);
        await form.locator('[name="confirm_password_change"]').check();
        await form.locator('button').click();
        await expect(page).toHaveURL(/notice=password-changed/);
        await expect(page.locator('.vault-page')).toHaveAttribute('data-vault-state', 'locked');
        await expect(page.locator('.operation-success')).toContainText(locale === 'en' ? 'revoked' : '撤銷');
        if (peer) {
          await expect(peer.locator('[data-secret-output]')).not.toHaveText(secret);
          await expect(peer.locator('.secret-reveal')).toBeDisabled();
          await peer.close(); peer = null;
        }
        const unlock = page.locator('form[action="/settings/vault/unlock"]');
        await unlock.locator('[name="master_password"]').fill(oldPassword);
        await unlock.locator('button').click();
        await expect(page.locator('.alert-error')).toBeVisible();
        await unlock.locator('[name="master_password"]').fill(newPassword);
        await unlock.locator('button').click();
        await expect(page.locator('.vault-page')).toHaveAttribute('data-vault-state', 'unlocked');
        await page.locator('.vault-rotation-details > summary').click();
        await page.screenshot({ path: `data/r13-vault-${locale}-${native ? 'native' : 'enhanced'}.png`, fullPage: true });
        await page.goto(appURL + '/settings/backup');
        const recovery = page.locator('a[href*="/settings/backup/files/projmemo-pre-vault-change-"]');
        await expect(recovery).toHaveCount(1);
        expect((await page.request.get(appURL + await recovery.getAttribute('href'))).status()).toBe(200);
      } finally { if (peer && !peer.isClosed()) await peer.close(); await context.close(); }
    });
  }
}
