(() => {
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (event.defaultPrevented || form.method?.toLowerCase() !== "post") return;
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
  window.addEventListener("pageshow", () => {
    document.querySelectorAll('[data-submitting="true"]').forEach((form) => {
      delete form.dataset.submitting; form.removeAttribute("aria-busy");
      form.querySelectorAll("[data-submit-disabled]").forEach((button) => {
        button.disabled = false; delete button.dataset.submitDisabled;
      });
    });
  });
})();
