(() => {
  const navigation = document.querySelector(".content-navigation");
  const content = document.getElementById("project-content");
  if (!navigation || !content) return;

  const header = document.querySelector(".site-header");
  const entries = [...navigation.querySelectorAll(".section-jumps a")]
    .map((link) => ({ link, section: document.getElementById(link.hash.slice(1)) }))
    .filter(({ section }) => section);
  if (!entries.length) return;

  document.documentElement.classList.add("project-detail-page");
  let currentId = null;
  let clickedId = null;
  let frame = null;
  let boundary = 0;
  const setCurrent = (id) => {
    currentId = id;
    entries.forEach(({ link, section }) => {
      if (section.id === id) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  };
  const update = () => {
    frame = null;
    const headerHeight = header ? header.getBoundingClientRect().height : 0;
    const navigationHeight = navigation.getBoundingClientRect().height;
    boundary = Math.ceil(headerHeight + navigationHeight + 12);
    document.documentElement.style.setProperty("--project-header-height", `${headerHeight}px`);
    document.documentElement.style.setProperty("--project-anchor-offset", `${boundary}px`);

    // An explicit jump wins until the user starts scrolling or changes the layout.
    // Native links keep hash/history and keyboard behavior, including without JS.
    if (clickedId) { setCurrent(clickedId); return; }
    const positions = entries.map((entry, order) => ({ ...entry, order,
      rect: entry.section.getBoundingClientRect(),
    }));
    const crossed = positions.filter(({ rect }) => rect.top <= boundary + 8 && rect.bottom > boundary);
    crossed.sort((a, b) => {
      if (Math.abs(a.rect.top - b.rect.top) > 2) return b.rect.top - a.rect.top;
      if (a.section.id === currentId) return -1;
      if (b.section.id === currentId) return 1;
      return a.order - b.order;
    });
    // Between sections, hold the previous section until the next heading crosses.
    const previous = positions.filter(({ rect }) => rect.top <= boundary + 8)
      .sort((a, b) => b.rect.top - a.rect.top || a.order - b.order);
    setCurrent((crossed[0] || previous[0] || positions[0]).section.id);
  };
  const schedule = () => {
    if (frame === null) frame = window.requestAnimationFrame(update);
  };
  const resumeTracking = () => { clickedId = null; schedule(); };
  const readHash = () => {
    const entry = entries.find(({ link }) => link.hash === window.location.hash);
    clickedId = entry ? entry.section.id : null;
    schedule();
  };

  entries.forEach(({ link, section }) => {
    link.addEventListener("click", (event) => {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      clickedId = section.id;
      setCurrent(clickedId);
      // Refresh the measured offset before the browser's default anchor action.
      update();
    });
  });
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", resumeTracking);
  window.addEventListener("hashchange", readHash);
  window.addEventListener("wheel", resumeTracking, { passive: true });
  window.addEventListener("touchstart", resumeTracking, { passive: true });
  // Scrollbar dragging is also manual navigation; no stored click should pin it.
  document.addEventListener("pointerdown", (event) => {
    if (!navigation.contains(event.target)) resumeTracking();
  });
  document.addEventListener("keydown", (event) => {
    const target = event.target;
    if (target instanceof Element && target.closest("input, textarea, select, [contenteditable]")) return;
    if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key)) resumeTracking();
  });
  document.addEventListener("toggle", resumeTracking, true);
  document.addEventListener("projmemo:detail-view-change", resumeTracking);
  if (typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(schedule);
    [header, navigation, content].filter(Boolean).forEach((element) => observer.observe(element));
  }
  readHash();
  update();
})();
