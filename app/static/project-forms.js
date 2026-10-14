(() => {
  const content = document.getElementById("project-content");
  const messagesElement = document.getElementById("content-form-messages");
  if (!content || !messagesElement) return;
  const messages = JSON.parse(messagesElement.textContent);
  const dialog = document.getElementById("content-discard-dialog");
  let pendingClose = null;
  const containers = [...content.querySelectorAll(".add-form, .item-actions")]
    .filter((container) => container.querySelector("form[data-content-form]"));
  const dirty = (form) => [...form.elements].some((control) => {
    if (!control.name || ["hidden", "submit", "button", "reset"].includes(control.type)) return false;
    if (control.type === "password") return control.value !== "";
    if (["checkbox", "radio"].includes(control.type)) return control.checked !== control.defaultChecked;
    if (control.tagName === "SELECT") {
      const options = [...control.options];
      const explicitDefault = options.some((option) => option.defaultSelected);
      return options.some((option, index) => option.selected !== (option.defaultSelected || !explicitDefault && index === 0));
    }
    return control.value !== control.defaultValue;
  });
  const finishClose = (container, returnFocus = true) => {
    const form = container.querySelector("form[data-content-form]");
    form.reset();
    // Even reset must never restore a password from an HTML default value.
    form.querySelectorAll('input[type="password"]').forEach((input) => { input.value = ""; });
    container.open = false;
    if (returnFocus) container.querySelector("summary").focus();
    return true;
  };
  const close = (container, returnFocus = true) => {
    if (!dirty(container.querySelector("form[data-content-form]"))) return finishClose(container, returnFocus);
    if (typeof dialog?.showModal === "function") {
      pendingClose = container; // DOM reference only; no copy of any field or password.
      dialog.showModal();
      return false;
    }
    return window.confirm(messages.discard) ? finishClose(container, returnFocus) : false;
  };
  if (typeof dialog?.showModal === "function") {
    dialog.querySelector("[data-keep-content]").addEventListener("click", () => { pendingClose = null; dialog.close(); });
    dialog.querySelector("[data-discard-content]").addEventListener("click", () => {
      const container = pendingClose;
      pendingClose = null;
      dialog.close();
      if (container) finishClose(container);
    });
    dialog.addEventListener("cancel", () => { pendingClose = null; });
  }
  containers.forEach((container) => {
    container.querySelectorAll("[data-cancel-content]").forEach((button) => {
      button.hidden = false;
      button.addEventListener("click", () => close(container));
    });
    container.querySelector("summary").addEventListener("click", (event) => {
      if (!container.open) return;
      event.preventDefault();
      close(container);
    });
  });
  // Closing an edit menu follows the same discard policy as its Cancel button.
  document.addEventListener("click", (event) => {
    if (dialog?.open) return;
    // Changing the view moves the same DOM; it is not a request to cancel drafts.
    if (event.target.closest?.("[data-detail-view]")) return;
    for (const container of containers) {
      if (!container.matches(".item-actions") || !container.open || container.contains(event.target)) continue;
      if (!close(container, false)) {
        event.preventDefault();
        event.stopPropagation();
        break;
      }
    }
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || dialog?.open) return;
    const containing = event.target.closest?.(".add-form, .item-actions");
    const current = containing && containers.includes(containing) && containing.open ? containing :
      [...containers].reverse().find((container) => container.matches(".item-actions") && container.open);
    if (!current) return;
    event.preventDefault();
    event.stopPropagation();
    close(current);
  });
})();
