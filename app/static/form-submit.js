(() => {
  const messagesNode = document.getElementById("submission-messages");
  const staleMessage = messagesNode?.textContent ? JSON.parse(messagesNode.textContent).stale : "This form may already have been submitted. Check the saved data and refresh before submitting new changes.";
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (event.defaultPrevented || form.method?.toLowerCase() !== "post") return;
    if (form.dataset.submissionStale === "true") {
      event.preventDefault();
      if (!form.querySelector(".submission-stale")) {
        const warning = document.createElement("p"); warning.className = "form-feedback submission-stale";
        warning.setAttribute("role", "alert"); warning.textContent = staleMessage; form.prepend(warning);
      }
      return;
    }
    if (form.dataset.submitting === "true") { event.preventDefault(); return; }
    form.dataset.submitting = "true";
    form.setAttribute("aria-busy", "true");
    const content = document.getElementById("project-content");
    if (content) {
      let input = form.querySelector('[name="_detail_view"]');
      if (!input) { input = document.createElement("input"); form.append(input); }
      input.type = "hidden"; input.name = "_detail_view"; input.value = content.dataset.view;
    }
    // Defer disabling so the browser includes the submitter (e.g. language).
    setTimeout(() => {
      if (event.defaultPrevented) { delete form.dataset.submitting; form.removeAttribute("aria-busy"); return; }
      form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach((button) => {
        if (!button.disabled) { button.dataset.submitDisabled = "true"; button.disabled = true; }
      });
    }, 0);
  });
  window.addEventListener("pageshow", (event) => {
    document.querySelectorAll('[data-submitting="true"]').forEach((form) => {
      // Back/forward can resurrect the old one-time token after a successful POST.
      // Keep newly edited fields visible instead of silently replaying that token.
      if (event?.persisted) form.dataset.submissionStale = "true";
      delete form.dataset.submitting; form.removeAttribute("aria-busy");
      form.querySelectorAll("[data-submit-disabled]").forEach((button) => {
        button.disabled = false; delete button.dataset.submitDisabled;
      });
    });
  });
})();
