const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/form-submit.js"), "utf8");

function harness() {
  const handlers = {}, pending = [], controls = [{ disabled: false, dataset: {} }, { disabled: true, dataset: {} }];
  const form = { method: "post", dataset: {}, attrs: {}, children: [],
    setAttribute(name, value) { this.attrs[name] = value; }, removeAttribute(name) { delete this.attrs[name]; },
    querySelector(selector) { return selector === ".submission-stale" ? this.children.find(c=>c.className?.includes("submission-stale")) || null : this.children.find(c=>c.name === "_detail_view") || null; },
    querySelectorAll(selector) { return selector === "[data-submit-disabled]" ? controls.filter(c => c.dataset.submitDisabled) : controls; },
    append(input) { this.children.push(input); },
    prepend(input) { this.children.unshift(input); },
  };
  const document = { addEventListener(name, callback) { handlers[name] = callback; },
    getElementById() { return { dataset: { view: "list" } }; }, createElement() { return {setAttribute(){}}; }, querySelectorAll() { return [form]; },
  };
  vm.runInNewContext(source, { document, window: { addEventListener(name, cb) { handlers[name] = cb; } }, setTimeout(cb) { pending.push(cb); } });
  const submit = () => { const event = { target: form, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } }; handlers.submit(event); return event; };
  return { form, controls, pending, submit, handlers };
}

test("only one native submission proceeds; disabling is deferred and return view retained", () => {
  const page = harness();
  assert.equal(page.submit().defaultPrevented, false);
  assert.equal(page.controls[0].disabled, false);
  assert.equal(page.submit().defaultPrevented, true);
  page.pending.shift()();
  assert.equal(page.controls[0].disabled, true);
  assert.equal(page.form.children[0].value, "list");
  page.handlers.pageshow();
  assert.equal(page.controls[0].disabled, false);
  assert.equal(page.controls[1].disabled, true); // Never enable expired vault controls.
  assert.equal(page.submit().defaultPrevented, false);
});

test("bfcache restores a submitted form without silently reusing its completed token", () => {
  const page = harness(); page.submit(); page.pending.shift()();
  page.handlers.pageshow({persisted:true});
  assert.equal(page.form.dataset.submissionStale,"true");
  assert.equal(page.submit().defaultPrevented,true);
  assert.match(page.form.children[0].textContent,/already have been submitted/);
  assert.equal(page.controls[0].disabled,false);
});

test("a later cancellation releases the UI lock without disabling controls", () => {
  const page = harness();
  const event = page.submit(); event.preventDefault();
  page.pending.shift()();
  assert.equal(page.controls[0].disabled, false);
  assert.equal(page.form.dataset.submitting, undefined);
});
