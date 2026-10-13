(() => {
  const messageElement = document.getElementById("vault-messages");
  if (!messageElement) return;
  const messages = JSON.parse(messageElement.textContent);
  const visibleSecrets = new Map();
  let revealGeneration = 0;

  const mask = (output, button) => {
    const timer = visibleSecrets.get(output);
    if (timer) window.clearTimeout(timer);
    visibleSecrets.delete(output);
    output.textContent = "••••••••••";
    if (button) {
      button.textContent = messages.show;
      button.disabled = false;
    }
  };

  document.querySelectorAll(".secret-reveal").forEach((button) => {
    button.addEventListener("click", async () => {
      const accountId = button.dataset.accountId;
      const output = document.querySelector(`[data-secret-output="${accountId}"]`);
      if (!output) return;

      if (visibleSecrets.has(output)) {
        mask(output, button);
        return;
      }

      button.disabled = true;
      button.textContent = messages.pending;
      const generation = revealGeneration;
      try {
        const response = await fetch(button.dataset.revealUrl, {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error(messages.readError);
        const payload = await response.json();
        if (typeof payload.secret !== "string") throw new Error(messages.formatError);

        if (generation !== revealGeneration) {
          payload.secret = "";
          return;
        }
        if (document.visibilityState !== "visible") {
          payload.secret = "";
          mask(output, button);
          return;
        }

        output.textContent = payload.secret;
        button.disabled = false;
        button.textContent = messages.hide;
        const timer = window.setTimeout(() => mask(output, button), 15_000);
        visibleSecrets.set(output, timer);
        payload.secret = "";
      } catch (error) {
        if (generation !== revealGeneration) return;
        button.disabled = false;
        button.textContent = messages.retry;
        button.title = error instanceof Error ? error.message : messages.genericError;
      }
    });
  });

  const maskAll = () => {
    revealGeneration += 1;
    document.querySelectorAll(".secret-reveal").forEach((button) => {
      const output = document.querySelector(`[data-secret-output="${button.dataset.accountId}"]`);
      if (output) mask(output, button);
    });
  };
  document.addEventListener("projmemo:detail-view-change", maskAll);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") maskAll();
  });
  window.addEventListener("pagehide", maskAll);
})();
