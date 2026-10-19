(() => {
  const node = document.getElementById("markdown-editor-messages");
  if (!node || typeof fetch !== "function" || typeof AbortController !== "function") return;
  const messages = JSON.parse(node.textContent);
  function enhance() {
    document.querySelectorAll("[data-markdown-editor]").forEach(editor => {
      if (editor.dataset.enhanced) return;
      editor.dataset.enhanced = "true";
      editor.querySelector("[data-editor-enhanced]").hidden = false;
      const textarea = editor.querySelector("textarea"), frame = editor.querySelector("iframe");
      const status = editor.querySelector("[data-preview-status]");
      let revision = 0, controller;
      const invalidate = () => {
        revision++; controller?.abort(); frame.hidden = true; frame.removeAttribute("srcdoc");
        status.textContent = messages.changed;
      };
      textarea.addEventListener("input", invalidate);
      textarea.form.addEventListener("reset", invalidate);
      editor.querySelector("[data-apply-template]").addEventListener("click", () => {
        const option = editor.querySelector("select").selectedOptions[0];
        if (!option?.value || (textarea.value.length && !window.confirm(messages.replace))) return;
        textarea.value = option.dataset.templateContent;
        textarea.dispatchEvent(new Event("input", { bubbles: true })); textarea.focus();
      });
      editor.querySelector("[data-markdown-preview]").addEventListener("click", async () => {
        const source = textarea.value;
        invalidate();
        if ([...source].length > 100000 || source.includes("\0")) { status.textContent = messages.limit; return; }
        const current = revision, active = new AbortController(); controller = active;
        const timeout = setTimeout(() => active.abort(), 10000);
        status.textContent = messages.loading;
        try {
          const response = await fetch("/editor/preview", {
            method: "POST", credentials: "same-origin", signal: active.signal,
            headers: { "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
              "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content },
            body: new URLSearchParams({ content_markdown: source }),
          });
          if (!response.ok) throw new Error("Preview unavailable");
          const result = await response.json();
          if (typeof result.document !== "string") throw new Error("Invalid preview");
          if (current !== revision || source !== textarea.value || !editor.isConnected) return;
          frame.srcdoc = result.document; frame.hidden = false; status.textContent = messages.ready;
        } catch (_) {
          if (current === revision && editor.isConnected) status.textContent = messages.failed;
        } finally { clearTimeout(timeout); }
      });
    });
  }
  enhance(); document.addEventListener("projmemo:notes-loaded", enhance);
})();
