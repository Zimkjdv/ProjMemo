const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/project-notes.js"), "utf8");

function harness(view = "cards") {
  const events = {};
  const frames = [];
  const heights = [32, 240, 32];
  const notes = heights.map((height, index) => ({
    open: true, dataset: {},
    body: { scrollHeight: height }, preview: { textContent: index === 2 ? "long ".repeat(100) : "note" },
    summary: { addEventListener(_, handler) { this.click = handler; } },
    querySelector(selector) { return selector === "summary" ? this.summary : selector === ".markdown-body" ? this.body : this.preview; },
  }));
  const content = { dataset: { view }, querySelectorAll: () => notes };
  vm.runInNewContext(source, {
    document: { getElementById: () => content, addEventListener(name, handler) { events[name] = handler; } },
    window: { requestAnimationFrame(handler) { frames.push(handler); return frames.length; }, addEventListener(name, handler) { events[name] = handler; } },
    getComputedStyle: () => ({ lineHeight: "22px" }),
  });
  const flush = () => { while (frames.length) frames.shift()(); };
  const click = index => notes[index].summary.click({ preventDefault() {} });
  return { notes, content, events, flush, click };
}

test("short cards stay readable, long rendered content and long text get summaries", () => {
  const page = harness();
  assert.deepEqual(page.notes.map(note => note.open), [true, false, false]);
  assert.deepEqual(page.notes.map(note => note.dataset.noteLong), ["false", "true", "true"]);
  assert.deepEqual(harness("list").notes.map(note => note.open), [false, false, false]);
});

test("manual expansion and collapse survive view changes and resize without storage", () => {
  const page = harness();
  page.click(1);
  page.click(0);
  page.content.dataset.view = "list";
  page.events["projmemo:detail-view-change"](); page.flush();
  assert.equal(page.notes[1].open, true);
  assert.equal(page.notes[0].open, false);
  page.content.dataset.view = "cards";
  page.events.resize(); page.flush();
  assert.equal(page.notes[1].open, true);
  assert.equal(page.notes[0].open, false);
});

test("width-dependent measurement updates untouched notes without overriding manual choices", () => {
  const page = harness();
  page.notes[0].body.scrollHeight = 180;
  page.events.resize(); page.flush();
  assert.equal(page.notes[0].open, false);
  page.click(0);
  page.notes[0].body.scrollHeight = 20;
  page.events.resize(); page.flush();
  assert.equal(page.notes[0].open, true);
  assert.equal(page.notes[0].dataset.noteLong, "false");
});

test("paged-out notes are not measured and page changes retain manual expansion", () => {
  const page = harness();
  page.click(1);
  const row = { hidden: true }, note = page.notes[1];
  note.closest = () => row;
  Object.defineProperty(note.body, "scrollHeight", { configurable: true, get() { throw Error("Hidden note measured"); } });
  page.events["projmemo:note-page-change"]();
  assert.doesNotThrow(() => page.flush());
  Object.defineProperty(note.body, "scrollHeight", { configurable: true, value: 240 });
  row.hidden = false;
  page.events["projmemo:note-page-change"](); page.flush();
  assert.equal(note.open, true);
});
