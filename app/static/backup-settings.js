(() => {
  const node = document.getElementById("backup-settings-messages");
  if (!node) return;
  const messages = JSON.parse(node.textContent);
  const form = document.querySelector(".backup-restore-form");
  if (form) {
    const input = form.querySelector('[name="backup_file"]');
    const button = form.querySelector("[data-backup-preview-button]");
    const status = form.querySelector("[data-backup-file-status]");
    const zone = form.querySelector("[data-backup-dropzone]");
    const pickerLabel = form.querySelector("[data-backup-pick-label]");
    let depth = 0;
    const showError = (message) => {
      input.setCustomValidity(message);
      button.disabled = true;
      status.textContent = message;
      status.hidden = false;
      status.dataset.state = "error";
    };
    const update = () => {
      input.setCustomValidity("");
      const files = input.files;
      if (files.length > 1) { showError(messages.multiple); return; }
      if (files.length && !files[0].size) { showError(messages.empty); return; }
      if (files.length && files[0].size > Number(input.dataset.maxBytes)) { showError(messages.large); return; }
      button.disabled = !files.length || form.dataset.submitting === "true";
      status.dataset.state = files.length ? "selected" : "empty";
      status.textContent = files.length
        ? `${files[0].name} · ${(files[0].size / 1048576).toFixed(2)} MB — ${messages.selected}` : "";
      status.hidden = !files.length;
    };
    input.addEventListener("change", update);
    form.addEventListener("reset", () => window.setTimeout(update, 0));
    window.addEventListener("pageshow", () => window.setTimeout(update, 0));
    zone.addEventListener("dragenter", (event) => { event.preventDefault(); depth++; zone.dataset.dragging = "true"; });
    zone.addEventListener("dragover", (event) => { event.preventDefault(); if (event.dataTransfer) event.dataTransfer.dropEffect = "copy"; });
    zone.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) delete zone.dataset.dragging; });
    zone.addEventListener("drop", (event) => {
      event.preventDefault(); depth = 0; delete zone.dataset.dragging;
      const files = event.dataTransfer?.files;
      if (!files?.length) return;
      if (files.length !== 1) { showError(messages.multiple); return; }
      try {
        const transfer = new DataTransfer(); transfer.items.add(files[0]); input.files = transfer.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      } catch (_) { showError(messages.unsupported); }
      // A drop only selects a file. It never reads its contents or submits it.
    });
    if (pickerLabel) { pickerLabel.hidden = false; zone.dataset.enhanced = "true"; }
    update();
  }
  const policy = document.querySelector(".backup-policy-form");
  if (policy) {
    const mode = policy.querySelector('[name="mode"]');
    const custom = policy.querySelector("[data-retention-custom]");
    const update = () => {
      custom.hidden = mode.value !== "custom";
      custom.querySelectorAll("input").forEach(input => { input.disabled = custom.hidden; });
    };
    mode.addEventListener("change", update);
    policy.addEventListener("reset", () => window.setTimeout(update, 0));
    window.addEventListener("pageshow", () => window.setTimeout(update, 0));
    update();
  }
})();
