const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = (name) => fs.readFileSync(path.join(__dirname, "../../app/static", name), "utf8");

function detailHarness(savedView, blockedStorage = false) {
  const makeParent = () => ({ children: [], append(element) {
    element.parentElement.children = element.parentElement.children.filter((child) => child !== element);
    this.children.push(element);
    element.parentElement = this;
  } });
  const main = makeParent();
  const side = makeParent();
  const sections = ["important-links", "project-notes", "access-accounts", "handover", "environment"]
    .map((id, i) => ({ id, parentElement: i < 2 ? main : side, draft: "unsaved", open: true }));
  main.children = sections.slice(0, 2);
  side.children = sections.slice(2);
  const content = Object.assign(makeParent(), {
    dataset: { view: "cards" },
    querySelectorAll(selector) { return selector === ".detail-panel" ? sections : sections.slice(1, 3); },
  });
  const buttons = ["cards", "list"].map((view) => ({
    dataset: { detailView: view }, attrs: {}, handlers: {}, active: false,
    classList: { toggle(_, value) { this.active = value; } },
    setAttribute(key, value) { this.attrs[key] = value; },
    addEventListener(key, handler) { this.handlers[key] = handler; },
  }));
  const viewSwitch = { hidden: true, querySelectorAll: () => buttons };
  const events = [];
  const document = {
    getElementById: () => content,
    querySelector: (selector) => selector === ".detail-view-switch" ? viewSwitch : null,
    querySelectorAll: () => ["important-links", "project-notes", "handover", "environment", "access-accounts"]
      .map((id) => ({ getAttribute: () => `#${id}` })),
    dispatchEvent: (event) => events.push(event.type),
  };
  let preference = savedView;
  const localStorage = {
    getItem() { if (blockedStorage) throw Error("blocked"); return preference; },
    setItem(_, value) { if (blockedStorage) throw Error("blocked"); preference = value; },
  };
  vm.runInNewContext(source("project-detail.js"), { document, localStorage, Event });
  return { content, sections, main, side, buttons, events, viewSwitch, preference: () => preference };
}

test("details use shortcut order, retain the same drafts, and return to the original columns", () => {
  const page = detailHarness(null);
  assert.equal(page.viewSwitch.hidden, false);
  page.buttons[1].handlers.click();
  assert.equal(page.content.dataset.view, "list");
  assert.deepEqual(page.content.children.map(({ id }) => id),
    ["important-links", "project-notes", "handover", "environment", "access-accounts"]);
  assert.equal(page.buttons[1].attrs["aria-pressed"], "true");
  assert.equal(page.preference(), "list");
  assert.ok(page.sections.every((section) => section.draft === "unsaved"));
  assert.equal(page.sections[1].open, false);
  page.buttons[0].handlers.click();
  assert.deepEqual(page.main.children.map(({ id }) => id), ["important-links", "project-notes"]);
  assert.deepEqual(page.side.children.map(({ id }) => id), ["access-accounts", "handover", "environment"]);
  assert.equal(page.sections[1].open, true);
  assert.equal(page.events.length, 2);
  page.buttons[0].handlers.click();
  assert.equal(page.events.length, 2); // Selecting the current view changes nothing.
});

test("saved details are restored; invalid or blocked storage still allows switching", () => {
  assert.equal(detailHarness("list").content.dataset.view, "list");
  assert.equal(detailHarness("invalid").content.dataset.view, "cards");
  const page = detailHarness(null, true);
  page.buttons[1].handlers.click();
  assert.equal(page.content.dataset.view, "list");
});

function vaultHarness() {
  const handlers = {};
  const button = { dataset: { accountId: "1", revealUrl: "/accounts/1/reveal" }, disabled: false,
    addEventListener: (_, handler) => { handlers.reveal = handler; } };
  const output = { textContent: "••••••••••" };
  const messages = { show: "Show", pending: "Pending", hide: "Hide", retry: "Retry" };
  const document = {
    visibilityState: "visible",
    getElementById: () => ({ textContent: JSON.stringify(messages) }),
    querySelectorAll: () => [button],
    querySelector: (selector) => selector === 'meta[name="csrf-token"]' ? { content: "fixture-csrf-token" } : output,
    addEventListener: (name, handler) => { handlers[name] = handler; },
  };
  const pending = [];
  const requests = [];
  const timers = new Map();
  let nextTimer = 0;
  const window = {
    setTimeout(handler) { timers.set(++nextTimer, handler); return nextTimer; },
    clearTimeout(id) { timers.delete(id); },
    addEventListener: (name, handler) => { handlers[name] = handler; },
  };
  vm.runInNewContext(source("vault.js"), {
    document, window, fetch: (url, options) => {
      requests.push({ url, options });
      return new Promise((resolve) => pending.push(resolve));
    },
  });
  const resolve = (index, secret = "fixture-secret") => pending[index]({ ok: true, json: async () => ({ secret }) });
  return { handlers, output, button, document, resolve, timers, requests };
}

test("password reveals submit the page CSRF token with same-origin credentials", async () => {
  const page = vaultHarness();
  const reveal = page.handlers.reveal();
  assert.equal(page.requests[0].options.headers["X-CSRF-Token"], "fixture-csrf-token");
  assert.equal(page.requests[0].options.credentials, "same-origin");
  page.resolve(0);
  await reveal;
});

test("view changes immediately mask revealed passwords and cancel their timers", async () => {
  const page = vaultHarness();
  const reveal = page.handlers.reveal();
  page.resolve(0);
  await reveal;
  assert.equal(page.output.textContent, "fixture-secret");
  page.handlers["projmemo:detail-view-change"]();
  assert.equal(page.output.textContent, "••••••••••");
  assert.equal(page.button.textContent, "Show");
  assert.equal(page.timers.size, 0);
});

test("a pending response cannot reveal again after switching, even during a newer request", async () => {
  const page = vaultHarness();
  const stale = page.handlers.reveal();
  page.handlers["projmemo:detail-view-change"]();
  assert.equal(page.button.disabled, false);
  const current = page.handlers.reveal();
  page.resolve(0, "stale-secret");
  await stale;
  assert.equal(page.output.textContent, "••••••••••");
  assert.equal(page.button.disabled, true);
  page.resolve(1, "current-secret");
  await current;
  assert.equal(page.output.textContent, "current-secret");
});

test("leaving the page or hiding the tab also invalidates pending responses", async () => {
  for (const event of ["visibilitychange", "pagehide"]) {
    const page = vaultHarness();
    const reveal = page.handlers.reveal();
    page.document.visibilityState = "hidden";
    page.handlers[event]();
    page.document.visibilityState = "visible";
    page.resolve(0);
    await reveal;
    assert.equal(page.output.textContent, "••••••••••");
    assert.equal(page.button.disabled, false);
  }
});
