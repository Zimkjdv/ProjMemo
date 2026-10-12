(() => {
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
