const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/vault-settings.js"), "utf8");

function harness(saved = false) {
  const handlers = {}, windowHandlers = {}, timers = [];
  const toggle = { checked: saved, defaultChecked: saved };
  const save = { disabled: false };
  const feedback = { hidden: true, classList: { toggle() {} } };
  const form = { dataset: {}, elements: { allow_secret_export: toggle },
    querySelector: selector => selector === "[data-policy-feedback]" ? feedback : save,
    addEventListener: (name, handler) => { handlers[name] = handler; } };
  const messages = { unchanged: "No changes", enable: "Not saved: on", disable: "Not saved: off" };
  const document = { querySelector: () => form, getElementById: () => ({ textContent: JSON.stringify(messages) }) };
  const window = { addEventListener: (name, handler) => { windowHandlers[name] = handler; }, setTimeout: handler => timers.push(handler) };
  vm.runInNewContext(source, { document, window });
  return { form, toggle, save, feedback, handlers, windowHandlers, flush: () => { while (timers.length) timers.shift()(); } };
}

for (const saved of [false, true]) {
  test(`saved ${saved}: change and revert track draft without pretending to save it`, () => {
    const page = harness(saved);
    assert.equal(page.save.disabled, true);
    assert.equal(page.feedback.textContent, "No changes");
    page.toggle.checked = !saved; page.handlers.input();
    assert.equal(page.save.disabled, false);
    assert.equal(page.feedback.textContent, saved ? "Not saved: off" : "Not saved: on");
    assert.equal(page.toggle.defaultChecked, saved);
    page.toggle.checked = saved; page.handlers.change();
    assert.equal(page.save.disabled, true);
    let prevented = false;
    page.handlers.submit({ preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
  });
}

test("reset and BFCache restoration track defaults without releasing an in-flight submit", () => {
  const page = harness();
  page.toggle.checked = true; page.handlers.change();
  page.form.dataset.submitting = "true"; page.handlers.change();
  assert.equal(page.save.disabled, true);
  delete page.form.dataset.submitting;
  page.windowHandlers.pageshow(); page.flush();
  assert.equal(page.save.disabled, false);
  page.form.dataset.submissionStale = "true";
  page.windowHandlers.pageshow(); page.flush();
  assert.equal(page.save.disabled, false); // Shared submission guard can explain/reject the stale token.
  assert.equal(page.form.dataset.submissionStale, "true");
  delete page.form.dataset.submissionStale;
  page.handlers.reset(); page.toggle.checked = false; page.flush();
  assert.equal(page.save.disabled, true);
  assert.equal(page.feedback.textContent, "No changes");
});

test("no policy form is a safe no-op", () => {
  vm.runInNewContext(source, { document: { querySelector: () => null, getElementById: () => null } });
});
