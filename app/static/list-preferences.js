(() => {
  const state = document.getElementById("list-preferences");
  if (!state) return;
  const key = "projmemo.listPreferences.v1";
  const normalize = (value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const result = {
      view: value.view === "list" ? "list" : "cards",
      page_size: [10, 20, 50].includes(value.page_size) ? value.page_size : 10,
      status: ["maintenance", "completed", "handover"].includes(value.status) ? value.status : "",
      // Only applied list filters; never read project content, forms, or secrets.
      q: typeof value.q === "string" && value.q.length <= 256 ? value.q : "",
    };
    for (const name of ["owner", "tag"]) {
      if (typeof value[name] === "string" && value[name].length <= 1000 && value[name].trim()) result[name] = value[name].trim();
    }
    if (value.search_scope === "all") result.search_scope = "all";
    if (["pending", "complete", "none"].includes(value.handover)) result.handover = value.handover;
    return result;
  };
  const current = normalize(JSON.parse(state.textContent));
  const url = new URL(window.location.href);
  // Trash/archive are explicit workspaces, not a remembered home-page preference.
  if (["archived", "trash"].includes(url.searchParams.get("collection"))) return;
  let saved = null;
  try {
    const raw = localStorage.getItem(key);
    if (raw && raw.length <= 4096) saved = normalize(JSON.parse(raw));
  } catch (_) { /* Explicit URLs and native list controls work without storage. */ }
  // A shared/bookmarked URL is authoritative, including explicit empty filters.
  const explicit = ["view", "page_size", "page", "q", "status", "collection", "owner", "tag", "search_scope", "handover"].some(name => url.searchParams.has(name));
  if (!explicit && saved && JSON.stringify(saved) !== JSON.stringify(current)) {
    url.searchParams.set("view", saved.view);
    url.searchParams.set("page_size", String(saved.page_size));
    url.searchParams.set("page", "1"); // Page numbers are not preferences.
    if (saved.q) url.searchParams.set("q", saved.q);
    if (saved.status) url.searchParams.set("status", saved.status);
    for (const name of ["owner", "tag", "search_scope", "handover"]) {
      if (saved[name]) url.searchParams.set(name, saved[name]);
    }
    window.location.replace(url.pathname + url.search + url.hash);
    return;
  }
  try { localStorage.setItem(key, JSON.stringify(current)); } catch (_) { /* Optional preference. */ }
  document.querySelector("[data-reset-list-preferences]")?.addEventListener("click", () => {
    try { localStorage.removeItem(key); } catch (_) { /* Native reset URL still works. */ }
  });
})();
