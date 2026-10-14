const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/note-pagination.js"), "utf8");

function harness(count = 75) {
  const events = {}, dispatched = [];
  const control = () => ({ disabled: false, addEventListener(name, fn) { this[name] = fn; } });
  const size = { ...control(), value: "20" }, previous = control(), next = control(), summary = {}, hint = {};
  const rows = Array.from({ length: count }, () => ({ hidden: false, action: { open: false }, draft: "Original draft", querySelector() { return this.action; } }));
  const controls = { hidden: true, querySelector(selector) { return { "[data-note-page-size]": size, "[data-note-page-previous]": previous, "[data-note-page-next]": next, "[data-note-page-summary]": summary, "[data-note-page-paused]": hint }[selector]; } };
  vm.runInNewContext(source, { Number, Event: class Event { constructor(type) { this.type = type; } }, document: {
    getElementById: id => id === "project-notes" ? { querySelector: () => controls, querySelectorAll: () => rows } : { textContent: JSON.stringify({ range: "Notes {first}–{last} of {count}" }) },
    addEventListener(name, fn) { events[name] = fn; }, dispatchEvent(event) { dispatched.push(event.type); },
  } });
  return { rows, size, previous, next, summary, hint, controls, events, dispatched, visible: () => rows.filter(row => !row.hidden).length };
}

test("long note lists page existing rows with accurate total and no persistence", () => {
  const page = harness();
  assert.equal(page.visible(), 20);
  assert.equal(page.summary.textContent, "Notes 1–20 of 75");
  assert.equal(page.previous.disabled, true);
  assert.equal(page.controls.hidden, false);
  page.next.click();
  assert.equal(page.summary.textContent, "Notes 21–40 of 75");
  assert.equal(page.rows[0].draft, "Original draft");
});

test("10/20/50 and all are bounded and selecting a size returns to page one", () => {
  const page = harness();
  for (const value of ["10", "50", "0", "invalid", "20"]) {
    page.size.value = value; page.size.change();
    const expected = value === "0" ? 75 : value === "invalid" ? 20 : Number(value);
    assert.equal(page.visible(), expected);
    assert.equal(page.previous.disabled, true);
  }
});

test("an open editor pauses paging and retains even unsaved draft values", () => {
  const page = harness();
  page.rows[0].action.open = true;
  page.rows[0].draft = "Unsaved edit";
  page.events.toggle();
  assert.equal(page.next.disabled, true);
  assert.equal(page.size.disabled, true);
  assert.equal(page.hint.hidden, false);
  page.next.click();
  page.size.value = "50"; page.size.change();
  assert.equal(page.visible(), 20);
  assert.equal(page.rows[0].hidden, false);
  assert.equal(page.rows[0].draft, "Unsaved edit");
  page.rows[0].action.open = false; page.events.toggle();
  assert.equal(page.next.disabled, false);
  assert.equal(page.hint.hidden, true);
});

test("last partial page is bounded and all paging emits a layout notification", () => {
  const page = harness(51);
  page.next.click(); page.next.click(); page.next.click();
  assert.equal(page.visible(), 11);
  assert.equal(page.summary.textContent, "Notes 41–51 of 51");
  assert.equal(page.next.disabled, true);
  page.previous.click();
  assert.equal(page.summary.textContent, "Notes 21–40 of 51");
  assert.ok(page.dispatched.every(type => type === "projmemo:note-page-change"));
});
