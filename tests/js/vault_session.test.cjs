const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/vault-session.js"), "utf8");

function harness() {
  let now = 0;
  let nextTimer = 0;
  const timers = new Map();
  const handlers = {};
  const pending = [];
  const dispatched = [];
  const initial = { configured: true, unlocked: true, remaining_seconds: 10, expires_at_ms: 10000, session_version: 1, allow_secret_export: false };
  const root = { dataset: {}, lang: "en" };
  const input = { type: "password", value: "unsaved fixture password", disabled: false };
  const button = { type: "button", disabled: false };
  const field = { hidden: false, matches: () => false, querySelectorAll: () => [input] };
  const reveal = { ...button, hidden: false, matches: () => true };
  const lockedLink = {};
  const label = { classList: { toggle() {} }, hasAttribute: () => false };
  const countdown = {};
  const noticeText = {};
  const notice = { hidden: true, querySelector: () => noticeText };
  const messages = { locked: "Locked", unlocked: "Unlocked", setup: "Setup", remaining: "Remaining", expires: "Expires", refresh: "Reload", unavailable: "Unavailable" };
  const queries = selector => {
    if (selector === "[data-vault-unlocked-only], .sensitive-export") return [field, reveal];
    if (selector === ".secret-reveal, input[name='secret_value']") return [reveal, input];
    if (selector === "[data-vault-locked-only]") return [lockedLink];
    if (selector === "[data-vault-state-label]") return [label];
    if (selector === "[data-vault-remaining]") return [countdown];
    return [];
  };
  const document = { documentElement: root, visibilityState: "visible",
    getElementById: () => ({ textContent: JSON.stringify({ status: initial, messages }) }),
    querySelector: () => notice, querySelectorAll: queries,
    dispatchEvent: event => dispatched.push(event.type), addEventListener: (name, handler) => { handlers[name] = handler; },
  };
  const channels = [];
  class Channel { constructor() { channels.push(this); } postMessage() {} close() { this.closed = true; } }
  const window = { setTimeout(callback, delay) { timers.set(++nextTimer, { callback, due: now + delay }); return nextTimer; },
    clearTimeout(id) { timers.delete(id); }, addEventListener: (name, handler) => { handlers[name] = handler; },
  };
  vm.runInNewContext(source, { document, window, performance: { now: () => now }, location: { pathname: "/projects/1", search: "" },
    BroadcastChannel: Channel, AbortController, Event, URLSearchParams, fetch: (url, options) => new Promise((resolve, reject) => pending.push({ url, options, resolve, reject })) });
  return { root, input, reveal, notice, noticeText, label, countdown, dispatched, handlers, channels, pending, document,
    async respond(index, status = initial) { pending[index].resolve({ ok: true, json: async () => status }); await new Promise(resolve => setImmediate(resolve)); },
    async reject(index) { pending[index].reject(new Error("Offline")); await new Promise(resolve => setImmediate(resolve)); },
    advance(value) { now = value; const due = [...timers].filter(([, timer]) => timer.due <= now); for (const [id, timer] of due) { if (timers.delete(id)) timer.callback(); } },
  };
}

test("the original remaining period expires, disables secrets and preserves non-secret page state", async () => {
  const page = harness();
  assert.equal(page.root.dataset.vaultSessionActive, "false");
  await page.respond(0);
  assert.equal(page.root.dataset.vaultSessionActive, "true");
  page.advance(10000);
  assert.equal(page.root.dataset.vaultSessionActive, "false");
  assert.equal(page.input.value, "");
  assert.equal(page.reveal.disabled, true);
  assert.equal(page.notice.hidden, false);
  assert.ok(page.dispatched.includes("projmemo:vault-invalidated"));
});

test("a cross-tab refresh invalidates reveals immediately and rejects an older unlocked status response", async () => {
  const page = harness();
  page.channels[0].onmessage({ data: { type: "refresh" } });
  assert.equal(page.reveal.disabled, true);
  await page.respond(1, { configured: true, unlocked: false, remaining_seconds: 0, session_version: 0, allow_secret_export: false });
  await page.respond(0);
  assert.equal(page.root.dataset.vaultSessionActive, "false");
  assert.equal(page.label.textContent, "Locked");
});

test("renewed sessions require explicit refresh; failures pause actions instead of reporting unlocked", async () => {
  const renewed = harness();
  await renewed.respond(0, { configured: true, unlocked: true, remaining_seconds: 900, session_version: 2, allow_secret_export: false });
  assert.equal(renewed.root.dataset.vaultSessionActive, "false");
  assert.equal(renewed.noticeText.textContent, "Reload");
  const offline = harness();
  await offline.reject(0);
  assert.equal(offline.root.dataset.vaultSessionActive, "false");
  assert.equal(offline.noticeText.textContent, "Unavailable");
});

test("visibility and bfcache restoration recheck the server before accepting secret actions", async () => {
  const page = harness();
  await page.respond(0);
  page.document.visibilityState = "hidden"; page.handlers.visibilitychange();
  assert.equal(page.root.dataset.vaultSessionActive, "false");
  page.document.visibilityState = "visible"; page.handlers.visibilitychange();
  await page.respond(1);
  assert.equal(page.root.dataset.vaultSessionActive, "true");
  page.handlers.pagehide();
  assert.equal(page.channels[0].closed, true);
  page.handlers.pageshow({ persisted: true });
  assert.equal(page.channels.length, 2);
  assert.equal(page.root.dataset.vaultSessionActive, "false");
});
