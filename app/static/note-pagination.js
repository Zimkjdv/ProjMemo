(() => {
  const panel = document.getElementById("project-notes");
  const state = document.getElementById("note-page-messages");
  const controls = panel?.querySelector("[data-note-pagination]");
  if (!controls || !state) return;
  const rows = [...panel.querySelectorAll(".note-list > .note-card")];
  const messages = JSON.parse(state.textContent);
  const sizeControl = controls.querySelector("[data-note-page-size]");
  const previous = controls.querySelector("[data-note-page-previous]");
  const next = controls.querySelector("[data-note-page-next]");
  const summary = controls.querySelector("[data-note-page-summary]");
  const pausedHint = controls.querySelector("[data-note-page-paused]");
  let size = 20, page = 0;
  const editing = () => rows.some(row => row.querySelector(".item-actions")?.open);
  const refreshButtons = () => {
    const paused = editing();
    if (pausedHint) pausedHint.hidden = !paused;
    sizeControl.disabled = paused;
    previous.disabled = paused || page === 0;
    next.disabled = paused || size === 0 || (page + 1) * size >= rows.length;
  };
  const render = () => {
    const count = size || rows.length;
    page = Math.min(page, Math.max(0, Math.ceil(rows.length / count) - 1));
    const first = page * count, last = Math.min(first + count, rows.length);
    rows.forEach((row, index) => { row.hidden = index < first || index >= last; });
    summary.textContent = messages.range.replace("{first}", String(first + 1)).replace("{last}", String(last)).replace("{count}", String(rows.length));
    refreshButtons();
    document.dispatchEvent(new Event("projmemo:note-page-change"));
  };
  previous.addEventListener("click", () => { if (editing() || page === 0) return; page--; render(); });
  next.addEventListener("click", () => { if (editing() || size === 0 || (page + 1) * size >= rows.length) return; page++; render(); });
  sizeControl.addEventListener("change", () => {
    if (editing()) { sizeControl.value = String(size); return; }
    const selected = Number(sizeControl.value);
    size = [0, 10, 20, 50].includes(selected) ? selected : 20;
    sizeControl.value = String(size);
    page = 0;
    render();
  });
  // Open edit forms cannot disappear during a page change; all drafts remain in DOM.
  document.addEventListener("toggle", refreshButtons, true);
  controls.hidden = false;
  render();
})();
