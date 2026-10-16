(() => {
  const section = document.getElementById("project-notes");
  const messageNode = document.getElementById("server-note-messages");
  if (!section || !messageNode || typeof fetch !== "function" || typeof DOMParser !== "function") return;
  const messages = JSON.parse(messageNode.textContent);
  let loading = false, revision = 0;
  const enhance = () => section.querySelectorAll("[data-note-page], [data-note-page-size]")
    .forEach(element => { element.dataset.pagingEnhanced = "true"; });
  const load = async (destination) => {
    if (loading) return;
    loading = true;
    let timeout;
    const disabledControls = [];
    try {
      if (!await window.ProjMemoDrafts.requestDiscard(section)) return;
      const initialRevision = revision;
      const url = new URL(destination, window.location.href);
      if (url.origin !== window.location.origin || url.pathname !== `/projects/${section.dataset.projectId}`) return;
      url.searchParams.set("detail_view", document.getElementById("project-content").dataset.view);
      const controller = new AbortController();
      timeout = window.setTimeout(() => controller.abort(), 10000);
      section.setAttribute("aria-busy", "true");
      section.querySelectorAll(".note-pagination button, .note-pagination select").forEach(control => {
        if (!control.disabled) { control.disabled = true; disabledControls.push(control); }
      });
      section.querySelector(".note-load-feedback").hidden = true;
      const response = await fetch(url.pathname + url.search, {
        credentials: "same-origin", headers: { "Accept": "text/html", "X-ProjMemo-Fragment": "notes" }, signal: controller.signal,
      });
      if (!response.ok || response.headers.get("X-ProjMemo-Fragment") !== "notes") throw new Error("Page unavailable");
      const parsed = new DOMParser().parseFromString(await response.text(), "text/html");
      const replacement = parsed.getElementById("project-notes");
      if (!replacement || replacement.dataset.projectId !== section.dataset.projectId || replacement.querySelector("script")) throw new Error("Invalid fragment");
      if (revision !== initialRevision && !await window.ProjMemoDrafts.requestDiscard(section)) return;
      // Only replace children: layout references and other drafts remain alive.
      section.replaceChildren(...replacement.childNodes);
      ["notesPage", "notesSize", "noteTotal"].forEach(key => { section.dataset[key] = replacement.dataset[key]; });
      section.classList.toggle("detail-panel-empty", replacement.classList.contains("detail-panel-empty"));
      const count = document.querySelector('.section-jumps a[href="#project-notes"] .jump-count');
      if (count) count.textContent = section.dataset.noteTotal;
      url.searchParams.set("notes_page", section.dataset.notesPage);
      url.searchParams.set("notes_size", section.dataset.notesSize);
      url.hash = "project-notes";
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
      enhance();
      document.dispatchEvent(new Event("projmemo:notes-loaded"));
      document.dispatchEvent(new Event("projmemo:note-page-change"));
      const heading = section.querySelector("h2");
      heading.setAttribute("tabindex", "-1"); heading.focus({ preventScroll: true });
      section.scrollIntoView({ block: "start" });
    } catch (_) {
      const feedback = section.querySelector(".note-load-feedback");
      feedback.textContent = messages.failed + " ";
      const fallback = document.createElement("a");
      fallback.href = destination; fallback.textContent = messages.fallback;
      feedback.append(fallback); feedback.hidden = false;
    } finally {
      disabledControls.forEach(control => { control.disabled = false; });
      window.clearTimeout(timeout); section.removeAttribute("aria-busy"); loading = false;
    }
  };
  section.addEventListener("input", () => { revision++; });
  section.addEventListener("change", () => { revision++; });
  section.addEventListener("click", (event) => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest?.("a[data-note-page]");
    if (!link) return;
    event.preventDefault(); load(link.href);
  });
  section.addEventListener("submit", (event) => {
    if (!event.target.matches("[data-note-page-size]")) return;
    event.preventDefault();
    const url = new URL(event.target.action, window.location.href);
    url.searchParams.set("notes_page", "1"); url.searchParams.set("notes_size", event.target.elements.notes_size.value);
    if (event.target.elements.checklist?.value === "pending") url.searchParams.set("checklist", "pending");
    load(url.href);
  });
  document.addEventListener("submit", (event) => {
    if (event.defaultPrevented || event.target.method.toLowerCase() !== "post") return;
    for (const name of ["notes_page", "notes_size"]) {
      let input = event.target.querySelector(`[name="_${name}"]`);
      if (!input) { input = document.createElement("input"); input.type = "hidden"; input.name = "_" + name; event.target.append(input); }
      input.value = section.dataset[name === "notes_page" ? "notesPage" : "notesSize"];
    }
  });
  enhance();
})();
