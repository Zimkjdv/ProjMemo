(() => {
  const visibleSecrets = new Map();

  const mask = (output, button) => {
    const timer = visibleSecrets.get(output);
    if (timer) window.clearTimeout(timer);
    visibleSecrets.delete(output);
    output.textContent = "••••••••••";
    if (button) {
      button.textContent = "顯示 15 秒";
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
      button.textContent = "解密中…";
      try {
        const response = await fetch(button.dataset.revealUrl, {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error("無法讀取密碼，請確認保管庫仍為解鎖狀態。");
        const payload = await response.json();
        if (typeof payload.secret !== "string") throw new Error("密碼回應格式錯誤。");

        if (document.visibilityState !== "visible") {
          payload.secret = "";
          mask(output, button);
          return;
        }

        output.textContent = payload.secret;
        button.disabled = false;
        button.textContent = "立即遮蔽";
        const timer = window.setTimeout(() => mask(output, button), 15_000);
        visibleSecrets.set(output, timer);
        payload.secret = "";
      } catch (error) {
        button.disabled = false;
        button.textContent = "顯示失敗，重試";
        button.title = error instanceof Error ? error.message : "無法讀取密碼";
      }
    });
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") {
      document.querySelectorAll(".secret-reveal").forEach((button) => {
        const accountId = button.dataset.accountId;
        const output = document.querySelector(`[data-secret-output="${accountId}"]`);
        if (output && visibleSecrets.has(output)) mask(output, button);
      });
    }
  });

  window.addEventListener("pagehide", () => {
    document.querySelectorAll(".secret-reveal").forEach((button) => {
      const output = document.querySelector(`[data-secret-output="${button.dataset.accountId}"]`);
      if (output && visibleSecrets.has(output)) mask(output, button);
    });
  });
})();
