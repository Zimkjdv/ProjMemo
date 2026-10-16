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
    const expansionChoices = new WeakMap();
    const expanders = [...content.querySelectorAll("[data-expand-in-cards]")];
    expanders.forEach((details) => {
      details.querySelector?.("summary")?.addEventListener("click", () => {
        expansionChoices.set(details, !details.open);
      });
    });
    const applyView = (view) => {
      const previousView = content.dataset.view;
      if (previousView !== view) {
        document.dispatchEvent(new Event("projmemo:detail-view-change"));
        if (view === "list") {
          listSections.forEach(({ element }) => content.append(element));
        } else {
          sections.forEach(({ element, parent }) => parent.append(element));
        }
        expanders.forEach((details) => {
          details.open = expansionChoices.has(details) ? expansionChoices.get(details) : view === "cards";
        });
        content.dataset.view = view;
      }
      buttons.forEach((button) => {
        const active = button.dataset.detailView === view;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
      });
      document.querySelectorAll(".checklist-filters a").forEach((link) => {
        const destination = new URL(link.href, window.location.href);
        destination.searchParams.set("detail_view", view);
        link.href = destination.pathname + destination.search + destination.hash;
      });
    };
    let savedView = "cards";
    try {
      if (localStorage.getItem(storageKey) === "list") savedView = "list";
    } catch (_) { /* View switching still works when browser storage is blocked. */ }
    const returnedView = content.dataset.returnView || new URLSearchParams(window.location.search).get("detail_view");
    if (["cards", "list"].includes(returnedView)) savedView = returnedView;
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
