(() => {
  const form = document.querySelector(".language-switch");
  if (!form) return;
  form.addEventListener("submit", () => {
    form.elements.return_to.value = document.documentElement.dataset.recoveryUrl || window.location.pathname + window.location.search + window.location.hash;
  });
})();
