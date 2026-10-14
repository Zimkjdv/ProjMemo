const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/project-forms.js"), "utf8");

function harness(kind = "add", confirmed = true, withDialog = false) {
  const handlers = {};
  const prompts = [];
  const controls = [
    { name: "title", type: "text", value: "Original", defaultValue: "Original" },
    { name: "note", type: "textarea", value: "line one\nline two", defaultValue: "line one\nline two" },
    { name: "is_secret", type: "checkbox", checked: false, defaultChecked: false },
    { name: "category", type: "select-one", tagName: "SELECT", options: [
      { selected: true, defaultSelected: false }, { selected: false, defaultSelected: false },
    ] },
    { name: "secret_value", type: "password", value: "", defaultValue: "" },
    { name: "csrf_token", type: "hidden", value: "changed", defaultValue: "old" },
  ];
  const form = { elements: controls, resets: 0,
    reset() {
      this.resets++;
      controls.forEach(control => {
        if (control.options) {
          const explicit = control.options.some(option => option.defaultSelected);
          control.options.forEach((option, index) => { option.selected = option.defaultSelected || !explicit && index === 0; });
        } else if (control.type === "checkbox") control.checked = control.defaultChecked;
        else control.value = control.defaultValue;
      });
    },
    querySelectorAll: () => controls.filter(control => control.type === "password"),
  };
  const summary = { focused: 0, focus() { this.focused++; }, addEventListener(_, handler) { this.click = handler; } };
  const button = { hidden: true, addEventListener(_, handler) { this.click = handler; } };
  const container = { open: true, matches: () => kind === "edit", contains: target => target.inside === container,
    querySelector: selector => selector === "summary" ? summary : form,
    querySelectorAll: () => [button],
  };
  const content = { querySelectorAll: () => [container] };
  const modalButtons = { keep: {}, discard: {} };
  Object.values(modalButtons).forEach(button => { button.addEventListener = (_, handler) => { button.click = handler; }; });
  const dialog = withDialog ? { open: false, showModal() { this.open = true; }, close() { this.open = false; },
    querySelector: selector => selector === "[data-keep-content]" ? modalButtons.keep : modalButtons.discard,
    addEventListener(_, handler) { this.cancel = handler; },
  } : null;
  vm.runInNewContext(source, { document: {
    getElementById: id => id === "project-content" ? content : id === "content-discard-dialog" ? dialog : { textContent: JSON.stringify({ discard: "Discard?" }) },
    addEventListener(name, handler) { handlers[name] = handler; },
  }, window: { confirm(message) { prompts.push(message); return confirmed; } } });
  const event = (inside = true) => ({ key: "Escape", prevented: false, stopped: false,
    target: { inside: inside ? container : null, closest: () => inside ? container : null },
    preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; },
  });
  return { controls, container, form, summary, button, prompts, handlers, event, dialog, modalButtons };
}

test("unchanged forms close without prompts or submit, returning focus to their entry", () => {
  const page = harness();
  assert.equal(page.button.hidden, false);
  page.button.click();
  assert.equal(page.container.open, false);
  assert.equal(page.form.resets, 1);
  assert.equal(page.prompts.length, 0);
  assert.equal(page.summary.focused, 1);
});

test("declining a discard keeps exact drafts and the form open", () => {
  const page = harness("add", false);
  page.controls[1].value = "unsaved\nmultiline";
  page.button.click();
  assert.equal(page.controls[1].value, "unsaved\nmultiline");
  assert.equal(page.container.open, true);
  assert.equal(page.form.resets, 0);
  assert.deepEqual(page.prompts, ["Discard?"]);
});

test("confirming discards changed fields and secrets but never re-enables expired password inputs", () => {
  const page = harness();
  page.controls[0].value = "Unsaved";
  page.controls[4].value = "fixture password";
  page.controls[4].defaultValue = "unsafe default must be cleared";
  page.controls[4].disabled = true;
  page.button.click();
  assert.equal(page.controls[0].value, "Original");
  assert.equal(page.controls[4].value, "");
  assert.equal(page.controls[4].disabled, true);
  assert.equal(page.container.open, false);
});

test("checkbox, select, and password-only changes require confirmation; restoring defaults is not dirty", () => {
  for (const change of [
    page => { page.controls[2].checked = true; },
    page => { page.controls[3].options[0].selected = false; page.controls[3].options[1].selected = true; },
    page => { page.controls[4].value = "fixture"; },
  ]) {
    const page = harness("add", false); change(page); page.button.click();
    assert.equal(page.prompts.length, 1);
    assert.equal(page.container.open, true);
  }
  const page = harness();
  page.controls[0].value = "Changed"; page.controls[0].value = "Original";
  page.button.click();
  assert.equal(page.prompts.length, 0);
});

test("explicit non-first select defaults are not reported as changes", () => {
  const page = harness();
  page.controls[3].options[0].selected = false;
  page.controls[3].options[1].selected = true;
  page.controls[3].options[1].defaultSelected = true;
  page.button.click();
  assert.equal(page.prompts.length, 0);
});

test("summary closing and Escape share the cancel policy without discarding rejected drafts", () => {
  const page = harness("edit", false);
  page.controls[0].value = "Unsaved";
  const click = page.event(); page.summary.click(click);
  assert.equal(click.prevented, true);
  assert.equal(page.container.open, true);
  const escape = page.event(); page.handlers.keydown(escape);
  assert.equal(escape.prevented, true);
  assert.equal(page.form.resets, 0);
  assert.equal(page.controls[0].value, "Unsaved");
});

test("outside edit-menu closing confirms changes and rejects the outside action if discard is declined", () => {
  const page = harness("edit", false);
  page.controls[0].value = "Unsaved";
  const outside = page.event(false); page.handlers.click(outside);
  assert.equal(outside.prevented, true);
  assert.equal(outside.stopped, true);
  assert.equal(page.container.open, true);
  const clean = harness("edit"); clean.handlers.click(clean.event(false));
  assert.equal(clean.container.open, false);
  assert.equal(clean.summary.focused, 0); // Do not steal focus from the outside target.
});

test("outside clicks do not cancel add drafts and opening a summary retains native behavior", () => {
  const page = harness("add", false);
  page.controls[0].value = "Unsaved";
  page.handlers.click(page.event(false));
  assert.equal(page.prompts.length, 0);
  assert.equal(page.container.open, true);
  page.container.open = false;
  const opening = page.event(); page.summary.click(opening);
  assert.equal(opening.prevented, false);
});

test("the accessible dialog keeps drafts until explicit discard and returns focus after closing", () => {
  const page = harness("add", true, true);
  page.controls[0].value = "Unsaved";
  page.controls[4].value = "fixture-only-password";
  page.button.click();
  assert.equal(page.dialog.open, true);
  assert.equal(page.prompts.length, 0);
  assert.equal(page.form.resets, 0);
  page.modalButtons.keep.click();
  assert.equal(page.dialog.open, false);
  assert.equal(page.controls[0].value, "Unsaved");
  page.button.click(); page.modalButtons.discard.click();
  assert.equal(page.form.resets, 1);
  assert.equal(page.controls[4].value, "");
  assert.equal(page.container.open, false);
  assert.equal(page.summary.focused, 1);
});

test("modal Escape and clicks do not retrigger underlying edit-menu closing", () => {
  const page = harness("edit", true, true);
  page.controls[0].value = "Unsaved";
  page.button.click();
  page.handlers.click(page.event(false));
  const escape = page.event(false); page.handlers.keydown(escape);
  assert.equal(escape.prevented, false); // Native dialog Escape handles the cancel.
  page.dialog.cancel(); page.dialog.close();
  assert.equal(page.container.open, true);
  assert.equal(page.form.resets, 0);
  page.button.click(); page.modalButtons.discard.click();
  assert.equal(page.container.open, false);
});

test("Escape closes a clean edit menu and returns focus without opening a dialog", () => {
  const page = harness("edit", true, true);
  const event = page.event(); page.handlers.keydown(event);
  assert.equal(page.container.open, false);
  assert.equal(page.summary.focused, 1);
  assert.equal(page.dialog.open, false);
  assert.equal(page.prompts.length, 0);
  assert.equal(event.prevented, true);
});

test("view buttons are not outside cancellation and retain dirty edit drafts", () => {
  const page = harness("edit", true, true);
  page.controls[0].value = "Retained draft";
  const event = page.event(false);
  event.target.closest = selector => selector === "[data-detail-view]" ? {} : null;
  page.handlers.click(event);
  assert.equal(page.dialog.open, false);
  assert.equal(page.container.open, true);
  assert.equal(page.controls[0].value, "Retained draft");
  assert.equal(event.prevented, false);
  assert.equal(page.form.resets, 0);
});
