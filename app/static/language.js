(() => {
  const form = document.querySelector(".language-switch");
  if (!form) return;
  form.addEventListener("submit", () => {
    form.elements.return_to.value = window.location.pathname + window.location.search + window.location.hash;
  });
})();
