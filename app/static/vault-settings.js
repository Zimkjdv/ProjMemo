(() => {
  const form = document.querySelector("[data-vault-policy-form]");
  const messagesNode = document.getElementById("vault-policy-messages");
  if (!form || !messagesNode) return;
  const messages = JSON.parse(messagesNode.textContent);
  const toggle = form.elements.allow_secret_export;
  const save = form.querySelector('button[type="submit"]');
  const feedback = form.querySelector("[data-policy-feedback]");
  const dirty = () => toggle.checked !== toggle.defaultChecked;
  const update = () => {
    const changed = dirty();
    // Never imply that a draft has changed the persisted server policy.
    feedback.hidden = false;
    feedback.textContent = changed ? (toggle.checked ? messages.enable : messages.disable) : messages.unchanged;
    feedback.classList.toggle("vault-policy-dirty", changed);
    // The shared guard owns stale-token rejection and its visible explanation.
    save.disabled = !changed || form.dataset.submitting === "true";
  };
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  form.addEventListener("reset", () => window.setTimeout(update, 0));
  form.addEventListener("submit", (event) => { if (!dirty()) event.preventDefault(); });
  // Run after the shared submission guard restores its buttons on BFCache return.
  window.addEventListener("pageshow", () => window.setTimeout(update, 0));
  update();
})();
