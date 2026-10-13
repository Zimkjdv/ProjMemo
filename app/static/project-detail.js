(() => {
  const content = document.getElementById("project-content");
  const viewSwitch = document.querySelector(".detail-view-switch");
  if (content && viewSwitch) {
    const storageKey = "projmemo.detailView";
    const sections = [...content.querySelectorAll(".detail-panel")].map((element) => ({
      element, parent: element.parentElement,
    }));
    // Move the existing sections, not copies: draft fields and event handlers survive.
    const listSections = [...document.querySelectorAll(".section-jumps a")]
      .map((link) => sections.find(({ element }) => `#${element.id}` === link.getAttribute("href")))
      .filter(Boolean);
    const buttons = [...viewSwitch.querySelectorAll("[data-detail-view]")];
    const applyView = (view) => {
      const previousView = content.dataset.view;
      if (previousView !== view) {
        document.dispatchEvent(new Event("projmemo:detail-view-change"));
        if (view === "list") {
          listSections.forEach(({ element }) => content.append(element));
        } else {
          sections.forEach(({ element, parent }) => parent.append(element));
        }
        content.querySelectorAll("[data-expand-in-cards]").forEach((details) => {
          details.open = view === "cards";
        });
        content.dataset.view = view;
      }
      buttons.forEach((button) => {
        const active = button.dataset.detailView === view;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
      });
    };
    let savedView = "cards";
    try {
      if (localStorage.getItem(storageKey) === "list") savedView = "list";
    } catch (_) { /* View switching still works when browser storage is blocked. */ }
    applyView(savedView);
    viewSwitch.hidden = false;
    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        const view = button.dataset.detailView;
        if (view !== "cards" && view !== "list") return;
        applyView(view);
        try { localStorage.setItem(storageKey, view); } catch (_) { /* Optional preference. */ }
      });
    });
  }

  const exportMenu = document.querySelector(".project-export");
  if (!exportMenu) return;

  document.addEventListener("click", (event) => {
    if (!exportMenu.contains(event.target)) exportMenu.open = false;
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && exportMenu.open) {
      exportMenu.open = false;
      exportMenu.querySelector("summary").focus();
    }
  });

  exportMenu.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      exportMenu.open = false;
    });
  });
})();
