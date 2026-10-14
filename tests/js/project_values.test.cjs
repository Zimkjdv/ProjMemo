const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/project-values.js"), "utf8");

function harness() {
  const events = {}, frames = [];
  const values = [200, 20].map(height => {
    const classes = new Set();
    const button = { hidden: true, attrs: {}, addEventListener(_, fn) { this.click = fn; }, setAttribute(k, v) { this.attrs[k] = v; } };
    const code = { textContent: "fixture-long-account\n  original whitespace", scrollHeight: height, clientHeight: 40 };
    return { dataset: {}, code, button,
      querySelector: selector => selector === "code[data-copy-value]" ? code : button,
      classList: { contains: name => classes.has(name), toggle(name) { if (classes.has(name)) { classes.delete(name); return false; } classes.add(name); return true; } },
    };
  });
  vm.runInNewContext(source, { document: {
    getElementById: id => id === "project-content" ? { querySelectorAll: selector => selector === "[data-readable-value]" ? values : [] } : { textContent: JSON.stringify({ expand: "Show full value", collapse: "Collapse value" }) },
    addEventListener(name, fn) { events[name] = fn; },
  }, window: { requestAnimationFrame(fn) { frames.push(fn); return frames.length; }, addEventListener(name, fn) { events[name] = fn; } } });
  return { values, events, flush() { while (frames.length) frames.shift()(); } };
}

test("only overflowing non-secret fields are clamped with visible accessible expansion", () => {
  const page = harness();
  assert.equal(page.values[0].button.hidden, false);
  assert.equal(page.values[1].button.hidden, true);
  assert.equal(page.values[0].dataset.readableEnhanced, "");
});

test("manual expansion survives layout changes without altering exact original copy text", () => {
  const page = harness(), value = page.values[0];
  const original = value.code.textContent;
  value.button.click();
  page.events["projmemo:detail-view-change"](); page.events.resize(); page.flush();
  assert.equal(value.classList.contains("readable-value-expanded"), true);
  assert.equal(value.button.attrs["aria-expanded"], "true");
  assert.equal(value.button.textContent, "Collapse value");
  assert.equal(value.code.textContent, original);
  value.button.click();
  assert.equal(value.button.attrs["aria-expanded"], "false");
});

test("controls disappear when the collapsed value fits after resize", () => {
  const page = harness();
  page.values[0].code.scrollHeight = 20;
  page.events.resize(); page.flush();
  assert.equal(page.values[0].button.hidden, true);
});
