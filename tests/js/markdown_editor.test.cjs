const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../app/static/markdown-editor.js'), 'utf8');

function harness() {
  const messages = { replace: 'replace?', loading: 'loading', failed: 'failed', ready: 'ready', changed: 'changed', limit: 'limit' };
  const events = {}, calls = [], pending = [], timers = new Map();
  const control = () => ({ hidden: true, handlers: {}, addEventListener(n, cb) { this.handlers[n] = cb; } });
  const form = control(), textarea = Object.assign(control(), { value: '', form, focus() {},
    dispatchEvent(event) { this.handlers[event.type]?.(event); } });
  const frame = Object.assign(control(), { removeAttribute(n) { delete this[n]; } });
  const status = {}, toolbar = control(), apply = control(), preview = control();
  const select = { selectedOptions: [{ value: 'test', dataset: { templateContent: 'TEMPLATE' } }] };
  const nodes = { textarea, iframe: frame, '[data-preview-status]': status, '[data-editor-enhanced]': toolbar,
    '[data-apply-template]': apply, '[data-markdown-preview]': preview, select };
  const editor = { dataset: {}, isConnected: true, querySelector(n) { return nodes[n]; } };
  const document = { getElementById() { return { textContent: JSON.stringify(messages) }; },
    querySelectorAll() { return [editor]; }, querySelector() { return { content: 'csrf-token' }; },
    addEventListener(n, cb) { events[n] = cb; } };
  let accept = false;
  vm.runInNewContext(source, { document, window: { confirm() { return accept; } },
    Event: class { constructor(type) { this.type = type; } }, AbortController, URLSearchParams,
    setTimeout(cb) { const id = timers.size + 1; timers.set(id, cb); return id; }, clearTimeout(id) { timers.delete(id); },
    fetch(url, options) { calls.push({ url, options }); return new Promise((resolve, reject) => pending.push({ resolve, reject })); } });
  return { textarea, frame, status, toolbar, editor, events, calls, pending, timers,
    apply: () => apply.handlers.click(), confirm: () => { accept = true; }, preview: () => preview.handlers.click(),
    edit(value) { textarea.value = value; textarea.handlers.input(); }, reset: () => form.handlers.reset() };
}

test('templates only replace drafts after confirmation; input invalidates preview', () => {
  const ui = harness(); assert.equal(ui.toolbar.hidden, false);
  ui.edit('existing'); ui.apply(); assert.equal(ui.textarea.value, 'existing');
  ui.confirm(); ui.apply(); assert.equal(ui.textarea.value, 'TEMPLATE');
  assert.equal(ui.frame.hidden, true); assert.equal(ui.calls.length, 0);
});

test('preview sends only Markdown with CSRF and same-origin credentials; binding is idempotent', async () => {
  const ui = harness(); ui.edit('原文 & <test>'); ui.events['projmemo:notes-loaded']();
  const result = ui.preview(); assert.equal(ui.calls.length, 1);
  const { url, options } = ui.calls[0];
  assert.equal(url, '/editor/preview'); assert.equal(options.credentials, 'same-origin');
  assert.equal(options.headers['X-CSRF-Token'], 'csrf-token');
  assert.deepEqual([...options.body.keys()], ['content_markdown']);
  assert.equal(options.body.get('content_markdown'), '原文 & <test>');
  ui.pending[0].resolve({ ok: true, json: async () => ({ document: '<p>Safe</p>' }) }); await result;
  assert.equal(ui.frame.srcdoc, '<p>Safe</p>'); assert.equal(ui.frame.hidden, false);
  ui.edit('new'); assert.equal(ui.frame.hidden, true); assert.equal(ui.frame.srcdoc, undefined);
});

test('out-of-order responses cannot reveal a stale preview or overwrite a draft', async () => {
  const ui = harness(); ui.edit('first'); const first = ui.preview();
  ui.edit('second'); const second = ui.preview();
  ui.pending[1].resolve({ ok: true, json: async () => ({ document: 'SECOND' }) }); await second;
  ui.pending[0].resolve({ ok: true, json: async () => ({ document: 'FIRST' }) }); await first;
  assert.equal(ui.frame.srcdoc, 'SECOND'); assert.equal(ui.textarea.value, 'second');
});

test('network errors, invalid responses and timeout retain drafts and offer retry', async () => {
  const ui = harness(); ui.edit('keep');
  const fail = ui.preview(); ui.pending[0].resolve({ ok: false }); await fail;
  assert.equal(ui.status.textContent, 'failed'); assert.equal(ui.textarea.value, 'keep');
  const invalid = ui.preview(); ui.pending[1].resolve({ ok: true, json: async () => ({}) }); await invalid;
  assert.equal(ui.status.textContent, 'failed');
  const timeout = ui.preview(); [...ui.timers.values()][0]();
  assert.equal(ui.calls[2].options.signal.aborted, true);
  ui.pending[2].reject(new Error('aborted')); await timeout;
  assert.equal(ui.status.textContent, 'failed'); assert.equal(ui.textarea.value, 'keep');
});

test('reset or removed paged editor invalidates a pending preview', async () => {
  for (const removed of [false, true]) {
    const ui = harness(); ui.edit('keep'); const result = ui.preview();
    if (removed) ui.editor.isConnected = false; else ui.reset();
    ui.pending[0].resolve({ ok: true, json: async () => ({ document: 'STALE' }) }); await result;
    assert.equal(ui.frame.hidden, true); assert.equal(ui.frame.srcdoc, undefined);
  }
});

test('preview rejects excessive Unicode length and NUL before requesting', async () => {
  const ui = harness();
  for (const invalid of ['x'.repeat(100001), 'a\0b']) {
    ui.edit(invalid); await ui.preview(); assert.equal(ui.status.textContent, 'limit');
  }
  assert.equal(ui.calls.length, 0);
});
