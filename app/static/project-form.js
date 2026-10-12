(() => {
  const form = document.getElementById("project-editor");
  const messageElement = document.getElementById("project-form-messages");
  if (!form || !messageElement) return;
  const messages = JSON.parse(messageElement.textContent);
  const fields = ["name", "description", "status", "owner", "tags"];
  const draftKey = `projmemo-language-draft:${window.location.pathname}`;

  // A language change reloads this page. Restore only that one in-tab draft.
  try {
    const saved = window.sessionStorage.getItem(draftKey);
    window.sessionStorage.removeItem(draftKey);
    const draft = saved ? JSON.parse(saved) : null;
    if (draft) {
      fields.forEach((name) => {
        const input = form.elements.namedItem(name);
        if (typeof draft[name] !== "string") return;
        if (name === "status" && ![...input.options].some((option) => option.value === draft[name])) return;
        input.value = draft[name];
      });
    }
  } catch {
    // Storage may be unavailable; the form and preview remain usable.
  }

  const splitValues = (text) => [...new Set(text.split(/[,，、\n]/).map((value) => value.trim()).filter(Boolean))];
  const tokens = new Map();
  let updatePreview = () => {};

  document.querySelectorAll("[data-token-field]").forEach((field) => {
    const editor = field.querySelector("input");
    const control = field.querySelector(".token-control");
    const list = field.querySelector(".token-values");
    let values = splitValues(editor.value);
    const canonical = document.createElement("input");
    canonical.type = "hidden";
    canonical.name = editor.name;
    field.append(canonical);
    editor.removeAttribute("name");
    editor.value = "";
    control.classList.add("is-enhanced");

    const currentValues = () => [...new Set([...values, ...splitValues(editor.value)])];
    const sync = () => {
      const current = currentValues();
      canonical.value = current.join(",");
      field.querySelectorAll("[data-token-value]").forEach((button) => {
        const selected = current.includes(button.dataset.tokenValue);
        button.disabled = selected;
        button.setAttribute("aria-pressed", String(selected));
      });
      updatePreview();
    };
    const render = () => {
      list.replaceChildren();
      values.forEach((value, index) => {
        const chip = document.createElement("span");
        chip.className = "token-chip";
        const text = document.createElement("span");
        text.textContent = value;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "×";
        remove.setAttribute("aria-label", messages.remove.replace("{value}", value));
        remove.addEventListener("click", () => {
          values.splice(index, 1);
          render();
          sync();
          editor.focus();
        });
        chip.append(text, remove);
        list.append(chip);
      });
    };
    const commit = (extra = "") => {
      values = [...new Set([...currentValues(), ...splitValues(extra)])];
      editor.value = "";
      render();
      sync();
    };
    editor.addEventListener("keydown", (event) => {
      if (event.isComposing || event.keyCode === 229) return;
      if (["Enter", ",", "，", "、"].includes(event.key)) {
        event.preventDefault();
        commit();
      } else if (event.key === "Backspace" && !editor.value && values.length) {
        event.preventDefault();
        values.pop();
        render();
        sync();
      }
    });
    editor.addEventListener("input", (event) => {
      if (!event.isComposing && /[,，、]/.test(editor.value)) commit();
      else sync();
    });
    editor.addEventListener("compositionend", () => {
      if (/[,，、]/.test(editor.value)) commit();
      else sync();
    });
    editor.addEventListener("blur", (event) => {
      // Committing can wrap chips and move the footer during a mouse click.
      // The submit handler commits pending values after Save is clicked.
      if (!field.contains(event.relatedTarget) && !event.relatedTarget?.closest(".editor-actions")) commit();
    });
    field.querySelectorAll("[data-token-value]").forEach((button) => {
      button.addEventListener("click", () => {
        commit(button.dataset.tokenValue);
        editor.focus();
      });
    });
    const suggestions = field.querySelector(".tag-suggestions");
    if (suggestions) suggestions.hidden = false;
    tokens.set(field.dataset.tokenField, { values: currentValues, commit });
    render();
    sync();
  });

  const renderBadges = (target, values, emptyLabel) => {
    target.replaceChildren();
    if (!values.length) {
      const empty = document.createElement("span");
      empty.className = "meta-empty";
      empty.textContent = emptyLabel;
      target.append(empty);
    } else {
      values.forEach((value) => {
        const badge = document.createElement("span");
        badge.className = "tag";
        badge.textContent = value;
        target.append(badge);
      });
    }
  };
  updatePreview = () => {
    const nameInput = form.elements.namedItem("name");
    const name = nameInput.value.trim();
    nameInput.setCustomValidity(name ? "" : messages.nameRequired);
    const heading = document.querySelector("[data-preview-name]");
    heading.textContent = name || messages.name;
    heading.classList.toggle("preview-placeholder", !name);
    document.querySelector("[data-preview-icon]").textContent = name ? [...name][0].toUpperCase() : "P";
    document.querySelector("[data-preview-description]").textContent = form.elements.namedItem("description").value.trim() || messages.description;
    const statusInput = form.elements.namedItem("status");
    const status = document.querySelector("[data-preview-status]");
    status.className = `status status-${statusInput.value}`;
    status.textContent = statusInput.selectedOptions[0].textContent;
    renderBadges(document.querySelector("[data-preview-owners]"), tokens.get("owner").values(), messages.ownerEmpty);
    renderBadges(document.querySelector("[data-preview-tags]"), tokens.get("tags").values(), messages.tagsEmpty);
  };
  ["name", "description", "status"].forEach((name) => {
    form.elements.namedItem(name).addEventListener("input", updatePreview);
  });
  form.addEventListener("submit", () => tokens.forEach((field) => field.commit()));
  document.querySelector(".language-switch")?.addEventListener("submit", () => {
    tokens.forEach((field) => field.commit());
    try {
      const draft = Object.fromEntries(fields.map((name) => [name, form.elements.namedItem(name).value]));
      window.sessionStorage.setItem(draftKey, JSON.stringify(draft));
    } catch {
      // Do not block language switching if browser storage is disabled.
    }
  });
  updatePreview();
})();
