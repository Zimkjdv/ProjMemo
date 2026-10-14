(() => {
  const content = document.getElementById("project-content");
  const messagesElement = document.getElementById("url-view-messages");
  if (!content || !messagesElement) return;
  const messages = JSON.parse(messagesElement.textContent);
  const addresses = [...content.querySelectorAll(".url-address")];
  let frame;
  const update = () => {
    frame = null;
    addresses.forEach((address) => {
      const code = address.querySelector("code[data-copy-value]");
      const button = address.querySelector("[data-expand-url]");
      if (!code || !button) return;
      address.dataset.urlEnhanced = "";
      button.hidden = !address.classList.contains("url-address-expanded") && code.scrollHeight <= code.clientHeight + 1;
    });
  };
  const schedule = () => { if (frame == null) frame = window.requestAnimationFrame(update); };
  addresses.forEach((address) => {
    const button = address.querySelector("[data-expand-url]");
    if (!button) return;
    button.addEventListener("click", () => {
      const expanded = address.classList.toggle("url-address-expanded");
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
