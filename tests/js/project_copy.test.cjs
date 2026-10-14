const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/project-copy.js"), "utf8");

function harness(writer, codeText = null) {
  const ids = {};
  const created = [];
  const makeNode = (tag) => ({ tag, dataset: {}, children: [], attrs: {}, hidden: true,
    append(...nodes) { this.children.push(...nodes); },
    setAttribute(name, value) { this.attrs[name] = value; },
    querySelector() { return this.children.find(node => node.tag === "span"); },
    addEventListener(_, handler) { this.click = handler; },
  });
  const field = { id: "account-username-1", textContent: '使用者 <literal> "quote"', matches: () => true };
  ids[field.id] = field;
  const button = makeNode("button"); button.dataset.copyTarget = field.id; button.append(makeNode("span"));
  const code = codeText === null ? null : { textContent: codeText, matches: () => true, parentElement: { before() {} } };
  if (code) Object.defineProperty(code, "id", { set(value) { ids[value] = code; } });
  const feedback = {};
  const messages = { copy: "Copy", code: "Copy code", pending: "Copying", success: "Copied", failure: "Failed: manually copy" };
  const content = { contains: target => Object.values(ids).includes(target), querySelectorAll: selector => selector === "[data-copy-target]" ? [button] : code ? [code] : [] };
  feedback.dataset = {};
  vm.runInNewContext(source, { document: {
    getElementById: id => id === "project-content" ? content : id === "copy-messages" ? { textContent: JSON.stringify(messages) } : id === "copy-feedback" ? feedback : ids[id],
    createElement(tag) { const node = makeNode(tag); created.push(node); return node; },
  }, navigator: { clipboard: writer ? { writeText: writer } : undefined }, window: { clearTimeout() {}, setTimeout() {} } });
  return { field, button, feedback, ids, created, code };
}

test("copy preserves full original characters and reports success only after the write completes", async () => {
  let resolve;
  let text;
  const page = harness(value => { text = value; return new Promise(done => { resolve = done; }); });
  const pending = page.button.click();
  assert.equal(page.button.disabled, true);
  assert.notEqual(page.feedback.textContent, "Copied");
  assert.equal(text, page.field.textContent);
  resolve(); await pending;
  assert.equal(page.feedback.textContent, "Copied");
  assert.equal(page.button.disabled, false);
});

test("denied or missing clipboard produces a manual-copy fallback without changing the source", async () => {
  for (const writer of [undefined, async () => { throw new Error("Denied"); }]) {
    const page = harness(writer);
    const original = page.field.textContent;
    await page.button.click();
    assert.equal(page.feedback.dataset.state, "failed");
    assert.equal(page.feedback.textContent, "Failed: manually copy");
    assert.equal(page.field.textContent, original);
  }
});

test("code copy keeps whitespace and newlines; password outputs are not accepted as targets", async () => {
  const writes = [];
  const page = harness(async text => { writes.push(text); }, "  echo '<demo>'\n\tsecond line\n");
  const codeButton = page.created.find(node => node.tag === "button");
  await codeButton.click();
  assert.equal(writes[0], page.code.textContent);
  page.ids.secret = { textContent: "must-not-copy", matches: () => false };
  page.button.dataset.copyTarget = "secret";
  await page.button.click();
  assert.equal(writes.length, 1);
});
