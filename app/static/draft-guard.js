(() => {
  const messages = document.getElementById("draft-guard-messages");
  if (!messages) return;
  const message = JSON.parse(messages.textContent).discard;
  const dialog = document.getElementById("draft-leave-dialog");
  let resolvePending = null, replaySubmit = false;
  let allowUnload = false;
  const controls = (form) => [...form.elements].filter((control) => control.name &&
    !["submit", "button", "reset"].includes(control.type) &&
    (control.type !== "hidden" || ["owner", "tags"].includes(control.name)));
  const dirty = (form) => {
    if (form.dataset.recoveredForm === "true") return true;
    return controls(form).some((control) => {
      if (control.type === "password") return control.value !== "";
      if (control.type === "file") return !!control.files?.length;
      if (["checkbox", "radio"].includes(control.type)) return control.checked !== control.defaultChecked;
      if (control.tagName === "SELECT") {
        const options = [...control.options], explicit = options.some(option => option.defaultSelected);
        return options.some((option, index) => option.selected !== (option.defaultSelected || !explicit && index === 0));
      }
      return control.value !== (control.dataset?.draftInitial ?? control.defaultValue);
    });
  };
  const forms = (root = document, except = null) => [...root.querySelectorAll("form")]
    .filter(form => form !== except && form.method.toLowerCase() === "post" && !form.classList.contains("language-switch"));
  const changed = (root = document, except = null) => forms(root, except).some(dirty);
  const confirmDiscard = (root = document, except = null) => !changed(root, except) || window.confirm(message);
  const requestDiscard = (root = document, except = null) => {
    if (!changed(root, except)) return Promise.resolve(true);
    if (typeof dialog?.showModal !== "function") return Promise.resolve(window.confirm(message));
    if (resolvePending) return Promise.resolve(false);
    return new Promise(resolve => { resolvePending = resolve; dialog.showModal(); });
  };
  if (typeof dialog?.showModal === "function") {
    const finish = (accepted) => { const resolve = resolvePending; resolvePending = null; dialog.close(); resolve?.(accepted); };
    dialog.querySelector("[data-stay-page]").addEventListener("click", () => finish(false));
    dialog.querySelector("[data-leave-page]").addEventListener("click", () => finish(true));
    dialog.addEventListener("cancel", () => finish(false));
  }
  const discard = (root = document) => forms(root).forEach(form => {
    form.reset(); delete form.dataset.recoveredForm;
    form.querySelectorAll('input[type="password"]').forEach(input => { input.value = ""; });
  });
  // Only DOM references and comparisons; never serialize drafts or secrets.
  window.ProjMemoDrafts = { dirty, changed, confirmDiscard, requestDiscard, discard };
  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest?.("a[href]");
    if (!link || link.target === "_blank" || link.hasAttribute("download") || link.matches("[data-note-page][data-paging-enhanced]")) return;
    const destination = new URL(link.href, window.location.href);
    if (destination.pathname === window.location.pathname && destination.search === window.location.search) return;
    if (/\/export\.(md|pdf)$/.test(destination.pathname)) return; // Attachment download keeps the page.
    if (changed() && typeof dialog?.showModal === "function") {
      event.preventDefault(); event.stopImmediatePropagation();
      requestDiscard().then(accepted => {
        if (accepted) { allowUnload = true; window.location.assign(link.href); }
      });
      return;
    }
    if (!confirmDiscard()) { event.preventDefault(); event.stopImmediatePropagation(); return; }
    allowUnload = true;
    setTimeout(() => { if (event.defaultPrevented) allowUnload = false; }, 0);
    setTimeout(() => { allowUnload = false; }, 2000);
  }, true);
  document.addEventListener("submit", (event) => {
    if (event.defaultPrevented) return;
    if (event.target.matches?.("[data-note-page-size][data-paging-enhanced]")) return;
    if (replaySubmit) { replaySubmit = false; allowUnload = true; return; }
    const except = event.target.classList.contains("language-switch") ? null : event.target;
    if (changed(document, except) && typeof dialog?.showModal === "function") {
      event.preventDefault(); event.stopImmediatePropagation();
      requestDiscard(document, except).then(accepted => {
        if (accepted) { replaySubmit = true; event.target.requestSubmit(event.submitter); }
      });
      return;
    }
    if (!confirmDiscard(document, except)) { event.preventDefault(); event.stopImmediatePropagation(); return; }
    allowUnload = true;
    setTimeout(() => { if (event.defaultPrevented) allowUnload = false; }, 0);
    setTimeout(() => { allowUnload = false; }, 2000);
  }, true);
  window.addEventListener("beforeunload", (event) => {
    if (allowUnload || !changed()) return;
    event.preventDefault(); event.returnValue = ""; // Browser-owned localized warning.
  });
  window.addEventListener("pageshow", () => { allowUnload = false; });
  window.addEventListener("pagehide", () => {
    document.querySelectorAll('input[type="password"]').forEach(input => { input.value = ""; });
  });
})();
