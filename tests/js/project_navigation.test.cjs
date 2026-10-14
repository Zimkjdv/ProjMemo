const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/project-navigation.js"), "utf8");

function harness(hash = "") {
  let scroll = 0;
  let headerHeight = 69;
  let navHeight = 80;
  const events = {};
  const frames = [];
  const properties = {};
  const sections = [
    ["important-links", 300, 550], ["project-notes", 600, 1600],
    ["handover", 700, 790], ["environment", 820, 1020], ["access-accounts", 300, 680],
  ].map(([id, top, bottom]) => ({ id, top, bottom,
    getBoundingClientRect() { return { top: this.top - scroll, bottom: this.bottom - scroll }; },
  }));
  const links = sections.map((section) => ({ hash: `#${section.id}`, attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
    removeAttribute(name) { delete this.attrs[name]; },
    addEventListener(name, handler) { this[name] = handler; },
  }));
  const header = { getBoundingClientRect: () => ({ height: headerHeight }) };
  const navigation = { querySelectorAll: () => links,
    getBoundingClientRect: () => ({ height: navHeight }), contains: (target) => links.includes(target),
  };
  const document = {
    documentElement: { classList: { add() {} }, style: { setProperty: (name, value) => { properties[name] = value; } } },
    querySelector: (selector) => selector === ".content-navigation" ? navigation : header,
    getElementById: (id) => id === "project-content" ? {} : sections.find((section) => section.id === id),
    addEventListener: (name, handler) => { events[name] = handler; },
  };
  const location = { hash };
  const window = { location, requestAnimationFrame: (callback) => { frames.push(callback); return frames.length; },
    addEventListener: (name, handler) => { events[name] = handler; },
  };
  vm.runInNewContext(source, { document, window, Element: class Element {} });
  const flush = () => { while (frames.length) frames.shift()(); };
  flush();
  return { sections, links, events, properties, location, flush,
    current: () => links.filter((link) => link.attrs["aria-current"] === "location").map((link) => link.hash),
    scrollTo(value, manual = true) { scroll = value; if (manual) events.wheel(); events.scroll(); flush(); },
    resize(headerValue, navValue) { headerHeight = headerValue; navHeight = navValue; events.resize(); flush(); },
  };
}

test("native jumps select one location; manual scrolling resumes heading tracking with stable ties", () => {
  const page = harness();
  assert.deepEqual(page.current(), ["#important-links"]);
  page.links[4].click({ button: 0 });
  page.scrollTo(150, false);
  assert.deepEqual(page.current(), ["#access-accounts"]);
  page.scrollTo(150);
  assert.deepEqual(page.current(), ["#access-accounts"]); // Same top; no flicker to URL.
  page.scrollTo(460);
  assert.deepEqual(page.current(), ["#project-notes"]);
  page.scrollTo(680);
  assert.deepEqual(page.current(), ["#environment"]);
  page.scrollTo(1050);
  assert.deepEqual(page.current(), ["#project-notes"]); // Tall note outlasts the short sidebar.
  assert.equal(page.location.hash, ""); // Scrollspy does not rewrite history.
});

test("existing bookmarks work; unknown hashes and modified clicks do not invent locations", () => {
  assert.deepEqual(harness("#environment").current(), ["#environment"]);
  const page = harness("#unknown");
  assert.deepEqual(page.current(), ["#important-links"]);
  page.links[1].click({ button: 0, ctrlKey: true });
  assert.deepEqual(page.current(), ["#important-links"]);
  page.location.hash = "#handover";
  page.events.hashchange(); page.flush();
  assert.deepEqual(page.current(), ["#handover"]);
});

test("resizing and expanding content refresh offsets; switching views re-evaluates moved sections", () => {
  const page = harness();
  assert.equal(page.properties["--project-anchor-offset"], "161px");
  page.resize(90, 110);
  assert.equal(page.properties["--project-header-height"], "90px");
  assert.equal(page.properties["--project-anchor-offset"], "212px");
  page.scrollTo(400);
  page.sections[1].top = 900;
  page.links[1].click({ button: 0 });
  page.events.toggle(); page.flush();
  assert.deepEqual(page.current(), ["#access-accounts"]);
  page.links[4].click({ button: 0 });
  page.events["projmemo:detail-view-change"]();
  page.sections[4].top = 2200;
  page.sections[4].bottom = 2600;
  page.flush();
  assert.deepEqual(page.current(), ["#important-links"]);
});
