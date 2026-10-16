const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/list-preferences.js"), "utf8");
const key = "projmemo.listPreferences.v1";
const defaults = { view: "cards", page_size: 10, status: "", q: "" };
const saved = { view: "list", page_size: 20, status: "maintenance", q: "Fixture & CJK 專案" };

function harness(url = "http://127.0.0.1:52878/", value = saved, current = defaults, blocked = false) {
  const data = new Map(value == null ? [] : [[key, typeof value === "string" ? value : JSON.stringify(value)]]);
  const replacements = [];
  const reset = { addEventListener(_, handler) { this.click = handler; } };
  const reads = [];
  vm.runInNewContext(source, { URL, document: {
    getElementById(id) { reads.push(id); return id === "list-preferences" ? { textContent: JSON.stringify(current) } : null; },
    querySelector(selector) { reads.push(selector); return selector === "[data-reset-list-preferences]" ? reset : null; },
  }, localStorage: {
    getItem(name) { if (blocked) throw Error("Unavailable"); return data.get(name); },
    setItem(name, value) { if (blocked) throw Error("Unavailable"); data.set(name, value); },
    removeItem(name) { if (blocked) throw Error("Unavailable"); data.delete(name); },
  }, window: { location: { href: url, replace(value) { replacements.push(value); } } } });
  return { data, replacements, reset, reads };
}

test("bare home restores the last applied state with encoded filters, hash, and page one", () => {
  const page = harness("http://127.0.0.1:52878/#home-intro-title");
  assert.equal(page.replacements.length, 1);
  const url = new URL(page.replacements[0], "http://127.0.0.1:52878");
  assert.equal(url.searchParams.get("q"), saved.q);
  assert.equal(url.searchParams.get("view"), "list");
  assert.equal(url.searchParams.get("page_size"), "20");
  assert.equal(url.searchParams.get("status"), "maintenance");
  assert.equal(url.searchParams.get("page"), "1");
  assert.equal(url.hash, "#home-intro-title");
});

test("any explicit list parameter takes precedence, including blank filters and a shared page", () => {
  for (const query of ["?q=", "?status=", "?view=cards", "?page_size=50", "?page=2", "?collection=active"]) {
    const page = harness("http://127.0.0.1:52878/" + query);
    assert.deepEqual(page.replacements, []);
    assert.deepEqual(JSON.parse(page.data.get(key)), defaults);
  }
});

test("only normalized applied list state is stored; no drafts, page numbers or content are read", () => {
  const page = harness("http://127.0.0.1:52878/?view=list", null, { ...saved, page: 8, secret_value: "never-store" });
  assert.deepEqual(JSON.parse(page.data.get(key)), saved);
  assert.deepEqual(page.reads, ["list-preferences", "[data-reset-list-preferences]"]);
  assert.equal(page.data.get(key).includes("never-store"), false);
});

test("corrupt or excessive storage, unknown enum values and denied storage retain native defaults", () => {
  for (const value of ["{bad", "x".repeat(2049), [], { view: "bad", page_size: -1, status: "bad", q: 33 }]) {
    const page = harness(undefined, value);
    assert.deepEqual(page.replacements, []);
  }
  assert.deepEqual(harness(undefined, saved, defaults, true).replacements, []);
  const longSearch = harness("http://127.0.0.1:52878/?q=x", null, { ...defaults, q: "x".repeat(257) });
  assert.equal(JSON.parse(longSearch.data.get(key)).q, "");
});

test("reset clears only list preferences and leaves the native reset link operational", () => {
  const page = harness("http://127.0.0.1:52878/?view=list", saved, saved);
  page.reset.click();
  assert.equal(page.data.has(key), false);
  const denied = harness("http://127.0.0.1:52878/?view=list", saved, saved, true);
  assert.doesNotThrow(() => denied.reset.click());
});

test("archive and trash never restore or overwrite active-list preferences", () => {
  for (const collection of ["archived", "trash"]) {
    const page = harness("http://127.0.0.1:52878/?collection=" + collection);
    assert.deepEqual(page.replacements, []);
    assert.deepEqual(JSON.parse(page.data.get(key)), saved);
    assert.deepEqual(page.reads, ["list-preferences"]);
  }
});
