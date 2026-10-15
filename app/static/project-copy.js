(() => {
  const content = document.getElementById("project-content");
  const messagesElement = document.getElementById("copy-messages");
  const feedback = document.getElementById("copy-feedback");
  if (!content || !messagesElement || !feedback) return;
  const messages = JSON.parse(messagesElement.textContent);
  let feedbackTimer;
  const boundButtons = new WeakSet(), processedCodes = new WeakSet();
  const bind = (button) => {
    if (boundButtons.has(button)) return;
    boundButtons.add(button);
    let stateTimer;
    button.hidden = false;
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target || !content.contains(target) || !target.matches("code[data-copy-value], .markdown-body pre > code")) return;
      button.disabled = true;
      const label = button.querySelector("span");
      if (label) label.textContent = messages.pending;
      let success = false;
      try {
        if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(target.textContent);
        success = true;
      } catch (_) { /* Keep the original selectable text as the fallback. */ }
      button.disabled = false;
      if (label) label.textContent = messages.copy;
      button.dataset.copyState = success ? "success" : "failed";
      window.clearTimeout(stateTimer);
      stateTimer = window.setTimeout(() => { delete button.dataset.copyState; }, 2000);
      feedback.textContent = success ? messages.success : messages.failure;
      feedback.dataset.state = success ? "success" : "failed";
      feedback.hidden = false;
      window.clearTimeout(feedbackTimer);
      feedbackTimer = window.setTimeout(() => { feedback.hidden = true; }, 4000);
    });
  };
  const initialize = () => {
    content.querySelectorAll("[data-copy-target]").forEach(bind);
    content.querySelectorAll(".markdown-body pre > code").forEach((code, index) => {
      if (processedCodes.has(code)) return;
      processedCodes.add(code);
      let id = `projmemo-code-${index}`;
      while (document.getElementById(id)) id += "-copy";
      code.id = id;
      const pre = code.parentElement;
      const wrapper = document.createElement("div");
      wrapper.className = "code-block";
      const toolbar = document.createElement("div");
      toolbar.className = "code-copy-toolbar";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "copy-button";
      button.dataset.copyTarget = id;
      button.setAttribute("aria-label", messages.code);
      const label = document.createElement("span");
      label.textContent = messages.code;
      button.append(label);
      toolbar.append(button);
      pre.before(wrapper);
      wrapper.append(toolbar, pre);
      bind(button);
    });
  };
  initialize();
  document.addEventListener("projmemo:notes-loaded", initialize);
})();
