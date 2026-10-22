const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../app/static/backup-settings.js'), 'utf8');

function harness() {
  const timers = [], handlers = {}, modeHandlers = {}, windowHandlers = {};
  const input = { files: [], dataset: { maxBytes: '104857600' }, setCustomValidity(value) { this.validity = value; },
    addEventListener(name, callback) { handlers[name] = callback; }, dispatchEvent(event) { handlers[event.type]?.(event); } };
  const button = {}, pickerLabel = {}, status = { dataset: {} }, zone = { dataset: {}, handlers: {}, addEventListener(name, callback) { this.handlers[name] = callback; } };
  const form = { dataset: {}, querySelector(selector) { return selector.includes('backup_file') ? input : selector.includes('button') ? button : selector.includes('status') ? status : selector.includes('pick-label') ? pickerLabel : zone; },
    addEventListener(name, callback) { handlers['form-' + name] = callback; } };
  const mode = { value: 'all', addEventListener(name, callback) { modeHandlers[name] = callback; } };
  const controls = [{ value: '10' }, { value: '30' }];
  const custom = { querySelectorAll: () => controls };
  const policy = { querySelector: selector => selector.includes('mode') ? mode : custom, addEventListener(name, callback) { modeHandlers['form-' + name] = callback; } };
  const messages = { empty: 'Empty', large: 'Large', multiple: 'Multiple', selected: 'Selected', unsupported: 'Unsupported' };
  const document = { getElementById: () => ({ textContent: JSON.stringify(messages) }), querySelector: selector => selector === '.backup-restore-form' ? form : policy };
  const window = { setTimeout: callback => timers.push(callback), addEventListener(name, callback) { (windowHandlers[name] ??= []).push(callback); } };
  class DataTransfer { constructor() { this.files = []; this.items = { add: file => this.files.push(file) }; } }
  vm.runInNewContext(source, { document, window, DataTransfer, Event });
  return { input, button, status, zone, form, mode, controls, custom, handlers, modeHandlers, windowHandlers,
    flush() { while (timers.length) timers.shift()(); }, drop(files) { zone.handlers.drop({ preventDefault() {}, dataTransfer: { files } }); } };
}

test('native picker requires one nonempty bounded file; display filenames as text only', () => {
  const page = harness();
  assert.equal(page.button.disabled, true);
  assert.equal(page.status.textContent, ''); assert.equal(page.status.hidden, true);
  for (const [file, message] of [[{ size: 0 }, 'Empty'], [{ size: 104857601 }, 'Large']]) {
    page.input.files = [file]; page.handlers.change(); assert.equal(page.input.validity, message); assert.equal(page.button.disabled, true);
    assert.equal(page.status.hidden, false);
  }
  page.input.files = [{ name: '<img>.sqlite3', size: 104857600 }]; page.handlers.change();
  assert.equal(page.input.validity, ''); assert.equal(page.button.disabled, false);
  assert.match(page.status.textContent, /<img>\.sqlite3/);
  assert.equal(page.status.hidden, false);
});

test('drop selects but never submits, and multiple files fail closed', () => {
  const page = harness();
  page.drop([{ name: 'fixture.sqlite3', size: 4096 }]);
  assert.equal(page.input.files[0].name, 'fixture.sqlite3'); assert.equal(page.button.disabled, false);
  page.drop([{ size: 5 }, { size: 5 }]);
  assert.equal(page.button.disabled, true); assert.equal(page.input.validity, 'Multiple');
  assert.equal(page.input.files.length, 1); // Previous selection was not silently replaced.
});

test('reset and bfcache recheck files without re-enabling a submitting form', () => {
  const page = harness(); page.drop([{ name: 'valid.db', size: 2 }]);
  page.form.dataset.submitting = 'true'; page.handlers.change(); assert.equal(page.button.disabled, true);
  delete page.form.dataset.submitting;
  page.input.files = []; page.handlers['form-reset'](); page.flush(); assert.equal(page.button.disabled, true);
  for (const callback of page.windowHandlers.pageshow) callback(); page.flush();
  assert.equal(page.status.textContent, ''); assert.equal(page.status.hidden, true);
});

test('all/custom visibility keeps numeric drafts and disables only hidden fields', () => {
  const page = harness(); assert.equal(page.custom.hidden, true); assert.ok(page.controls.every(control => control.disabled));
  page.mode.value = 'custom'; page.modeHandlers.change(); assert.equal(page.custom.hidden, false);
  page.controls[0].value = '7'; page.mode.value = 'all'; page.modeHandlers.change();
  page.mode.value = 'custom'; page.modeHandlers.change(); assert.equal(page.controls[0].value, '7');
  assert.ok(page.controls.every(control => !control.disabled));
});
