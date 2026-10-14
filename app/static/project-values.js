(() => {
  const content = document.getElementById("project-content");
  const state = document.getElementById("value-view-messages");
  if (!content || !state) return;
  const messages = JSON.parse(state.textContent);
  const values = [...content.querySelectorAll("[data-readable-value]")];
  let frame;
  const update = () => {
    frame = null;
    values.forEach((value) => {
      const code = value.querySelector("code[data-copy-value]");
      const button = value.querySelector("[data-expand-value]");
      if (!code || !button) return;
      value.dataset.readableEnhanced = "";
      button.hidden = !value.classList.contains("readable-value-expanded") && code.scrollHeight <= code.clientHeight + 1;
    });
  };
  const schedule = () => { if (frame == null) frame = window.requestAnimationFrame(update); };
  values.forEach((value) => {
    const button = value.querySelector("[data-expand-value]");
    if (!button) return;
    button.addEventListener("click", () => {
      const expanded = value.classList.toggle("readable-value-expanded");
      button.setAttribute("aria-expanded", String(expanded));
      button.textContent = expanded ? messages.collapse : messages.expand;
      update();
    });
  });
  document.addEventListener("projmemo:detail-view-change", schedule);
  window.addEventListener("resize", schedule);
  if (document.fonts?.ready) document.fonts.ready.then(schedule);
  update();
})();
