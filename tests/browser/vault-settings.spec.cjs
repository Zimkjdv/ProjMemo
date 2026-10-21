const { test, expect, language } = require('./fixtures.cjs');

const master = 'synthetic vault UI master phrase';
const policyForm = 'form[action="/settings/vault/export-policy"]';

async function setup(page) {
  const form = page.locator('form[action="/settings/vault/setup"]');
  await form.locator('[name="master_password"]').fill(master);
  await form.locator('[name="confirm_password"]').fill(master);
  await form.locator('button').click();
  await expect(page.locator('.vault-page')).toHaveAttribute('data-vault-state', 'unlocked');
}

async function aligned(page) {
  const layout = await page.locator('.vault-workspace').evaluate(element => {
    const cards = [...element.children].map(card => card.getBoundingClientRect());
    const rules = [...document.querySelectorAll('.vault-guidelines > li')].map(rule => rule.getBoundingClientRect());
    return { heights: cards.map(card => card.height), tops: cards.map(card => card.y),
      ruleTops: rules.map(rule => rule.y), overflow: document.documentElement.scrollWidth > innerWidth };
  });
  expect(Math.abs(layout.heights[0] - layout.heights[1])).toBeLessThan(1);
  expect(layout.tops[0]).toBe(layout.tops[1]);
  expect(new Set(layout.ruleTops).size).toBe(1);
  expect(layout.overflow).toBe(false);
}

for (const locale of ['zh-Hant', 'en']) {
  for (const native of [false, true]) {
    test.describe(`${locale} ${native ? 'native' : 'enhanced'} vault settings`, () => {
      test.use({ javaScriptEnabled: !native });
      test('single badge, accessible switch, saved/draft policy, desktop layout and locked safeguards', async ({ page, appURL }) => {
        await language(page, appURL, locale);
        await page.goto(appURL + '/settings/vault');
        await expect(page.locator('.header-nav [aria-current="page"]')).toHaveAttribute('href', '/settings/vault');
        await expect(page.locator('[data-vault-state-label]')).toHaveCount(1);
        await expect(page.locator('.vault-emblem svg')).toHaveCount(1);
        await expect(page.locator('.vault-panel-heading > .vault-section-icon')).toHaveCount(2);
        await aligned(page);
        await setup(page);
        if (!native) await expect(page.locator('html')).toHaveAttribute('data-vault-session-active', 'true');
        await expect(page.locator('[data-vault-state-label]')).toHaveCount(1);
        await expect(page.getByRole('timer')).toHaveText(/^(15:00|14:\d{2})$/);
        await expect(page.locator('.vault-facts > div')).toHaveCount(4);
        await expect(page.locator('.vault-rule-critical')).toContainText(locale === 'en' ? 'Irreversible' : '不可逆');
        expect(await page.locator('.vault-rule-critical').evaluate(element => getComputedStyle(element).borderTopColor)).toBe('rgb(233, 155, 155)');
        await expect(page.locator('.vault-panel-heading > .vault-section-icon')).toHaveCount(3); // R13 retained.
        for (const width of [1280, 1920]) {
          await page.setViewportSize({ width, height: 1100 });
          await aligned(page);
          const flow = await page.locator('.vault-export-flow').evaluate(element => {
            const label = element.querySelector(':scope > span').getBoundingClientRect();
            const steps = [...element.querySelectorAll('li')].map(step => step.getBoundingClientRect());
            return { labelTop: label.top, labelRight: label.right, stepTops: steps.map(step => step.top),
              firstLeft: steps[0].left, lastRight: steps.at(-1).right, right: element.getBoundingClientRect().right };
          });
          expect(flow.stepTops.every(top => Math.abs(top - flow.labelTop) < 1)).toBe(true);
          expect(flow.firstLeft).toBeGreaterThanOrEqual(flow.labelRight);
          expect(flow.lastRight).toBeLessThanOrEqual(flow.right + 1);
          await page.screenshot({ path: `data/vault-ui-${locale}-${native ? 'native' : 'enhanced'}-${width}.png`, fullPage: true });
        }
        const toggle = page.getByRole('switch');
        const save = page.locator(policyForm + ' button[type="submit"]');
        await expect(toggle).not.toBeChecked();
        if (native) await expect(save).toBeEnabled();
        else {
          await expect(save).toBeDisabled();
          await expect(page.locator('[data-policy-feedback]')).toHaveText(locale === 'en' ? 'No changes' : '尚無變更');
          expect(await page.locator('[data-policy-feedback]').evaluate(element => ({
            display: getComputedStyle(element).display, background: getComputedStyle(element).backgroundColor,
            dotWidth: getComputedStyle(element, '::before').width,
          }))).toEqual({ display: 'flex', background: 'rgb(246, 248, 251)', dotWidth: '6px' }); // Flex items are blockified.
        }
        const colors = await save.evaluate(element => ({ color: getComputedStyle(element).color, background: getComputedStyle(element).backgroundColor }));
        expect(colors).toEqual({ color: 'rgb(255, 255, 255)', background: 'rgb(56, 87, 214)' });
        // Keyboard space operates the real checkbox, including without JS.
        await toggle.focus(); await toggle.press('Space');
        await expect(toggle).toBeChecked(); await expect(save).toBeEnabled();
        await expect(page.locator('#vault-policy-current')).toContainText(locale === 'en' ? 'Off' : '關閉');
        if (!native) {
          await expect(page.locator('[data-policy-feedback]')).toContainText(locale === 'en' ? 'Not saved' : '尚未儲存');
          await expect(page.locator('[data-policy-feedback]')).toHaveClass(/vault-policy-dirty/);
          await toggle.press('Space'); await expect(save).toBeDisabled();
          await expect(page.locator('[data-policy-feedback]')).not.toHaveClass(/vault-policy-dirty/);
          await toggle.press('Space'); await expect(save).toBeEnabled();
        }
        await save.click();
        await expect(page.getByRole('switch')).toBeChecked();
        await expect(page.locator('#vault-policy-current')).toContainText(locale === 'en' ? 'On' : '已開啟');
        await page.locator('.vault-lock-button').click();
        await expect(page.locator('.vault-page')).toHaveAttribute('data-vault-state', 'locked');
        await page.getByRole('switch').uncheck(); // Turning off is allowed while locked.
        await save.click(); await expect(page.getByRole('switch')).not.toBeChecked();
        await page.getByRole('switch').check(); // Turning on still requires server-side unlock.
        await save.click();
        await expect(page.locator('.alert-error')).toBeVisible();
        await expect(page.getByRole('switch')).not.toBeChecked();
        await expect(page.locator('#vault-policy-current')).toContainText(locale === 'en' ? 'Off' : '關閉');
      });
    });
  }

  test(`${locale}: real countdown, cross-tab lock and unavailable status hide the timer safely`, async ({ page, appURL }) => {
    await language(page, appURL, locale);
    await page.goto(appURL + '/settings/vault'); await setup(page);
    await expect(page.locator('html')).toHaveAttribute('data-vault-session-active', 'true');
    const before = Number(await page.locator('[data-vault-progress]').getAttribute('value'));
    await expect.poll(async () => Number(await page.locator('[data-vault-progress]').getAttribute('value'))).toBeLessThan(before);
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-vault-session-active', 'true');
    expect(Number(await page.locator('[data-vault-progress]').getAttribute('value'))).toBeLessThanOrEqual(before);
    const peer = await page.context().newPage();
    try {
      await peer.goto(appURL + '/settings/vault');
      await peer.locator('.vault-lock-button').click();
      await expect(page.getByRole('timer')).toBeHidden();
      await expect(page.locator('.vault-lock-button')).toBeHidden();
      await expect(page.locator('[data-vault-state-label]')).toHaveText(locale === 'en' ? 'Locked' : '已鎖定');
    } finally { await peer.close(); }
    await page.reload();
    const unlock = page.locator('form[action="/settings/vault/unlock"]');
    await unlock.locator('[name="master_password"]').fill(master); await unlock.locator('button').click();
    await expect(page.locator('html')).toHaveAttribute('data-vault-session-active', 'true');
    await page.route('**/settings/vault/status', route => route.abort());
    // A genuine server-confirmation failure (not a fabricated successful status).
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await expect(page.getByRole('timer')).toBeHidden();
    await expect(page.locator('[data-vault-session-notice]')).toContainText(locale === 'en' ? 'unavailable' : '暫時無法');
  });
}
