const { test: base, expect } = require('@playwright/test');
const { spawn } = require('node:child_process');
const path = require('node:path');
const readline = require('node:readline');
const fs = require('node:fs');

const root = path.resolve(__dirname, '../..');
const test = base.extend({
  appURL: async ({}, use) => {
    const python = process.env.PROJMEMO_TEST_PYTHON || path.join(root,
      process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
    if (!fs.existsSync(python)) throw new Error('Set PROJMEMO_TEST_PYTHON to an existing locked test venv');
    const child = spawn(python, ['-m', 'tests.browser.server'], {
      cwd: root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUTF8: '1' },
    });
    let errors = '';
    child.stderr.on('data', chunk => { errors = (errors + chunk).slice(-4000); });
    const lines = readline.createInterface({ input: child.stdout });
    try {
      const url = await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('Fixture startup timed out: ' + errors)), 20000);
        child.once('error', error => { clearTimeout(timer); reject(error); });
        child.once('exit', () => { clearTimeout(timer); reject(new Error('Fixture stopped: ' + errors)); });
        lines.once('line', line => {
          clearTimeout(timer);
          try {
            const value = JSON.parse(line).url;
            if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(value)) throw new Error('Unexpected fixture URL');
            resolve(value);
          } catch (error) { reject(error); }
        });
      });
      for (let attempt = 0; ; attempt++) {
        try { if ((await fetch(url + '/health/ready')).ok) break; } catch {}
        if (attempt === 100) throw new Error('Fixture readiness timed out: ' + errors);
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      await use(url);
    } finally {
      lines.close();
      // EOF asks the Python fixture to stop gracefully, including TemporaryDirectory cleanup.
      child.stdin.end();
      if (child.exitCode === null) {
        await Promise.race([
          new Promise(resolve => child.once('exit', resolve)),
          new Promise(resolve => setTimeout(resolve, 5000)),
        ]);
      }
      if (child.exitCode === null) { child.kill(); throw new Error('Fixture did not shut down gracefully'); }
    }
  },
  page: async ({ page, appURL }, use) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    // Keep test data loopback-only. Fixture links must never be visited externally.
    await page.route('**/*', route => new URL(route.request().url()).origin === appURL
      ? route.continue() : route.abort());
    await use(page);
    expect(errors, 'uncaught browser errors').toEqual([]);
  },
});

async function language(page, appURL, value) {
  await page.goto(appURL + '/');
  await page.locator(`.language-switch button[value="${value}"]`).click();
  await expect(page.locator('html')).toHaveAttribute('lang', value);
}

async function submit(form) {
  await form.locator('button[type="submit"]').first().click();
}

module.exports = { test, expect, language, submit };
