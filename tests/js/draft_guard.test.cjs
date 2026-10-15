const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/draft-guard.js"), "utf8");

function harness(accept = false, withDialog = false) {
  const handlers = {}, prompts = [], timers = [];
  const text = { name: "title", type: "text", value: "Original", defaultValue: "Original" };
  const password = { name: "secret_value", type: "password", value: "", defaultValue: "" };
  const owner = { name: "owner", type: "hidden", value: "Team", defaultValue: "Team", dataset: { draftInitial: "Team" } };
  const form = { method: "post", dataset: {}, elements: [text, password, owner],
    classList: { contains: () => false }, reset() { text.value = "Original"; }, querySelectorAll: () => [password] };
  const language = { classList: { contains: () => true } };
  const modalButtons = [{}, {}];
  modalButtons.forEach(button => { button.addEventListener = (_, cb) => { button.click = cb; }; });
  const dialog = { open: false, showModal() { this.open = true; }, close() { this.open = false; },
    querySelector(selector) { return modalButtons[selector === "[data-stay-page]" ? 0 : 1]; }, addEventListener(_, cb) { this.cancel = cb; } };
  const document = { getElementById: id => id === "draft-leave-dialog" ? withDialog ? dialog : null : ({ textContent: JSON.stringify({ discard: "Discard?" }) }),
    querySelectorAll: selector => selector === "form" ? [form] : [password], addEventListener: (key, cb) => { handlers[key] = cb; } };
  const window = { location: { href: "http://127.0.0.1/projects/1", pathname: "/projects/1", search: "" },
    addEventListener: (key, cb) => { handlers[key] = cb; }, confirm: (msg) => { prompts.push(msg); return accept; } };
  vm.runInNewContext(source, { document, window, URL, setTimeout(cb) { timers.push(cb); } });
  const event = (target) => ({ target, button: 0, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopImmediatePropagation() {} });
  const link = (href, extra = {}) => ({ href, target: "", hasAttribute: () => false, matches: () => false, ...extra });
  const click = (value, extra = {}) => { const e = Object.assign(event({ closest: () => value }), extra); handlers.click(e); return e; };
  return { handlers, form, text, password, owner, window, prompts, timers, event, language, link, click, document, dialog, modalButtons };
}

test("declining navigation/language leaves exact draft; reload uses native beforeunload", () => {
  const p = harness(); p.text.value = "Draft"; p.password.value = "Transient";
  assert.equal(p.click(p.link("http://127.0.0.1/")).defaultPrevented, true);
  const e = p.event(p.language); p.handlers.submit(e);
  assert.equal(e.defaultPrevented, true);
  assert.equal(p.text.value, "Draft"); assert.equal(p.password.value, "Transient");
  const unload = p.event(); p.handlers.beforeunload(unload);
  assert.equal(unload.defaultPrevented, true);
});

test("accessible modal keeps drafts on cancel and replays only the chosen submitter after confirmation", async () => {
  const p = harness(false, true); p.text.value = "Draft";
  const submitter = { value: "en" }, event = p.event(p.language); event.submitter = submitter;
  p.language.requestSubmit = button => { assert.equal(button, submitter); p.handlers.submit(p.event(p.language)); };
  p.handlers.submit(event); assert.equal(p.dialog.open, true); assert.equal(event.defaultPrevented, true);
  p.modalButtons[0].click(); await Promise.resolve();
  assert.equal(p.text.value, "Draft"); assert.equal(p.dialog.open, false);
  p.handlers.submit(Object.assign(p.event(p.language), { submitter }));
  p.modalButtons[1].click(); await Promise.resolve();
  assert.equal(p.dialog.open, false); assert.equal(p.prompts.length, 0);
});

test("self-submit is allowed, but other dirty forms guard submits; accepted leave avoids duplicate prompt", () => {
  const p = harness(true); p.text.value = "Draft";
  const save = p.event(p.form); p.handlers.submit(save);
  assert.equal(save.defaultPrevented, false); assert.equal(p.prompts.length, 0);
  p.handlers.pageshow();
  assert.equal(p.click(p.link("http://127.0.0.1/settings/backup")).defaultPrevented, false);
  assert.equal(p.prompts.length, 1);
  const unload = p.event(); p.handlers.beforeunload(unload); assert.equal(unload.defaultPrevented, false);
  p.handlers.pageshow();
  const next = p.event(); p.handlers.beforeunload(next); assert.equal(next.defaultPrevented, true);
});

test("same-page anchors, new tabs, exports, and note partial paging do not discard the page", () => {
  const p = harness(); p.text.value = "Draft";
  p.click(p.link("http://127.0.0.1/projects/1#handover"));
  p.click(p.link("http://127.0.0.1/"), { ctrlKey: true });
  p.click(p.link("http://127.0.0.1/projects/1/export.pdf"));
  p.click(p.link("http://127.0.0.1/projects/1?notes_page=2", { matches: () => true }));
  assert.equal(p.prompts.length, 0); assert.equal(p.text.value, "Draft");
});

test("token-only changes and recovered drafts are tracked; discard clears passwords without storage", () => {
  const p = harness(); p.owner.value = p.owner.defaultValue = "Updated team";
  assert.equal(p.window.ProjMemoDrafts.changed(), true);
  p.owner.value = "Team"; p.form.dataset.recoveredForm = "true";
  assert.equal(p.window.ProjMemoDrafts.changed(), true);
  p.password.value = "Never persist"; p.window.ProjMemoDrafts.discard();
  assert.equal(p.password.value, ""); assert.equal(p.form.dataset.recoveredForm, undefined);
  p.password.value = "Clear on hide"; p.handlers.pagehide(); assert.equal(p.password.value, "");
  assert.doesNotMatch(source, /localStorage|sessionStorage|JSON\.stringify/);
});
