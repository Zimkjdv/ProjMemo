const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/project-urls.js"), "utf8");

function harness() {
  const events = {};
  const frames = [];
  const addresses = [200, 20].map(height => {
    const classes = new Set();
    const button = { hidden: true, attrs: {}, addEventListener(_, handler) { this.click = handler; }, setAttribute(name, value) { this.attrs[name] = value; } };
    const code = { textContent: "https://example.invalid/full-untruncated-value", scrollHeight: height, clientHeight: 40 };
    return { dataset: {}, code, button,
      classList: { contains: name => classes.has(name), toggle(name) { if (classes.has(name)) { classes.delete(name); return false; } classes.add(name); return true; } },
      querySelector: selector => selector === "code[data-copy-value]" ? code : button,
    };
  });
  vm.runInNewContext(source, { document: {
    getElementById: id => id === "project-content" ? { querySelectorAll: () => addresses } : { textContent: JSON.stringify({ expand: "Show full URL", collapse: "Collapse URL" }) },
    addEventListener(name, handler) { events[name] = handler; },
  }, window: { requestAnimationFrame(handler) { frames.push(handler); return frames.length; }, addEventListener(name, handler) { events[name] = handler; } } });
  return { addresses, events, flush() { while (frames.length) frames.shift()(); } };
}

test("only overflowing addresses get a full-value toggle, with the original copy target intact", () => {
  const page = harness();
  assert.equal(page.addresses[0].button.hidden, false);
  assert.equal(page.addresses[1].button.hidden, true);
  assert.equal(page.addresses[0].code.textContent, "https://example.invalid/full-untruncated-value");
});

test("URL expansion uses explicit accessible state and survives view and width changes", () => {
  const page = harness();
  const address = page.addresses[0];
  address.button.click();
  assert.equal(address.button.attrs["aria-expanded"], "true");
  assert.equal(address.button.textContent, "Collapse URL");
  page.events["projmemo:detail-view-change"](); page.flush();
  page.events.resize(); page.flush();
  assert.equal(address.classList.contains("url-address-expanded"), true);
  address.button.click();
  assert.equal(address.button.attrs["aria-expanded"], "false");
  assert.equal(address.button.textContent, "Show full URL");
});

test("collapsed address controls disappear when the entire text fits the new width", () => {
  const page = harness();
  page.addresses[0].code.scrollHeight = 20;
  page.events.resize(); page.flush();
  assert.equal(page.addresses[0].button.hidden, true);
});
