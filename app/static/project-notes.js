(() => {
  const content = document.getElementById("project-content");
  if (!content) return;
  const notes = [...content.querySelectorAll("[data-note-content]")];
  const choices = new WeakMap();
  let frame;
  const update = () => {
    frame = null;
    notes.forEach((note) => {
      const body = note.querySelector(".markdown-body");
      const preview = note.querySelector("[data-note-summary]");
      if (!body || !preview) return;
      // Measure the complete rendered body, never crop a table or a code block.
      note.open = true;
      const lineHeight = parseFloat(getComputedStyle(body).lineHeight) || 22;
      const long = body.scrollHeight > lineHeight * 3 + 12 || preview.textContent.length > 260;
      note.dataset.noteLong = String(long);
      note.open = choices.has(note) ? choices.get(note) : content.dataset.view !== "list" && !long;
    });
  };
  const schedule = () => {
    if (frame == null) frame = window.requestAnimationFrame(update);
  };
  notes.forEach((note) => {
    note.querySelector("summary").addEventListener("click", (event) => {
      event.preventDefault();
      choices.set(note, !note.open);
      note.open = !note.open;
    });
  });
  document.addEventListener("projmemo:detail-view-change", schedule);
  window.addEventListener("resize", schedule);
  if (document.fonts?.ready) document.fonts.ready.then(schedule);
  update();
})();
