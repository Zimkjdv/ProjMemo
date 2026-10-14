(() => {
  let channel = typeof BroadcastChannel === "function" ? new BroadcastChannel("projmemo-vault-state") : null;
  // A completed redirect, not a submitted form, signals confirmed server changes.
  if (location.pathname === "/settings/vault" || (location.pathname === "/settings/backup" && new URLSearchParams(location.search).get("restored") === "1")) {
    channel?.postMessage({ type: "refresh" });
  }
  const configElement = document.getElementById("vault-session-state");
  if (!configElement) { channel?.close(); return; }
  const { status: initial, messages } = JSON.parse(configElement.textContent);
  let status = initial;
  let deadline = performance.now() + initial.remaining_seconds * 1000;
  let requestVersion = 0;
  let tickTimer;
  let pollTimer;
  const notice = document.querySelector("[data-vault-session-notice]");
  const invalidate = () => {
    document.documentElement.dataset.vaultSessionActive = "false";
    document.dispatchEvent(new Event("projmemo:vault-invalidated"));
    document.querySelectorAll(".secret-reveal, input[name='secret_value']").forEach((control) => { control.disabled = true; });
  };
  const usable = () => status.unlocked && status.session_version === initial.session_version && initial.unlocked && deadline > performance.now();
  const updateControls = () => {
    const active = usable();
    document.documentElement.dataset.vaultSessionActive = String(active);
    document.querySelectorAll("[data-vault-unlocked-only], .sensitive-export").forEach((element) => {
      element.hidden = !active;
      const controls = element.matches("button, input") ? [element] : [...element.querySelectorAll("button, input")];
      controls.forEach((control) => { control.disabled = !active; if (!active && control.type === "password") control.value = ""; });
    });
    document.querySelectorAll("[data-vault-locked-only]").forEach((element) => { element.hidden = active; });
    document.querySelectorAll("[data-vault-state-label]").forEach((element) => {
      const short = element.hasAttribute("data-vault-state-short");
      element.textContent = !status.configured ? (short ? messages.shortSetup : messages.setup) : status.unlocked ? (short ? messages.shortUnlocked : messages.unlocked) : (short ? messages.shortLocked : messages.locked);
      element.classList.toggle("vault-state-open", status.unlocked);
    });
    document.querySelectorAll("[data-vault-session]").forEach((element) => element.classList.toggle("vault-inline-open", status.unlocked));
    document.querySelectorAll("[data-vault-icon-state]").forEach((element) => { element.hidden = (element.dataset.vaultIconState === "unlocked") !== status.unlocked; });
    document.querySelectorAll("[data-vault-state-description]").forEach((element) => { element.textContent = !status.configured ? messages.setupHint : status.unlocked ? messages.unlockedHint : messages.lockedHint; });
  };
  const showNotice = (message) => {
    if (!notice) return;
    notice.hidden = false;
    notice.querySelector("span").textContent = message;
  };
  const tick = () => {
    window.clearTimeout(tickTimer);
    const remaining = Math.max(0, deadline - performance.now());
    const seconds = Math.ceil(remaining / 1000);
    document.querySelectorAll("[data-vault-remaining]").forEach((element) => {
      element.hidden = !status.unlocked;
      const time = status.expires_at_ms ? new Date(status.expires_at_ms).toLocaleTimeString(document.documentElement.lang, { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
      element.textContent = `${messages.remaining} ${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")} · ${messages.expires} ${time}`;
    });
    if (status.unlocked && remaining <= 0) {
      invalidate();
      status = { ...status, unlocked: false };
      updateControls();
      showNotice(messages.refresh);
      void sync();
    } else if (status.unlocked) {
      tickTimer = window.setTimeout(tick, Math.min(1000, remaining));
    }
  };
  const sync = async () => {
    const version = ++requestVersion;
    const started = performance.now();
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch("/settings/vault/status", { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" }, signal: controller.signal });
      if (!response.ok) throw new Error("Status unavailable");
      const next = await response.json();
      if (typeof next.unlocked !== "boolean" || typeof next.configured !== "boolean" || !Number.isFinite(next.remaining_seconds) || next.remaining_seconds < 0 || !Number.isInteger(next.session_version)) throw new Error("Invalid status");
      if (version !== requestVersion) return;
      if (next.session_version !== status.session_version || next.unlocked !== status.unlocked || !next.unlocked) invalidate();
      status = next;
      // Subtract the full request duration rather than extending the server TTL.
      deadline = started + next.remaining_seconds * 1000;
      updateControls();
      if (next.session_version !== initial.session_version || next.configured !== initial.configured || next.allow_secret_export !== initial.allow_secret_export) showNotice(messages.refresh);
      else if (notice) notice.hidden = true;
      tick();
    } catch (_) {
      if (version !== requestVersion) return;
      invalidate();
      status = { ...status, unlocked: false };
      updateControls();
      showNotice(messages.unavailable);
    } finally { window.clearTimeout(timeout); }
  };
  const poll = () => {
    window.clearTimeout(pollTimer);
    if (document.visibilityState === "visible") { void sync(); pollTimer = window.setTimeout(poll, 10000); }
  };
  if (channel) channel.onmessage = (event) => { if (event.data?.type === "refresh") { invalidate(); void sync(); } };
  document.addEventListener("visibilitychange", () => {
    invalidate();
    requestVersion += 1;
    if (document.visibilityState === "visible") poll();
    else window.clearTimeout(pollTimer);
  });
  window.addEventListener("focus", () => { invalidate(); void sync(); });
  window.addEventListener("pagehide", () => { invalidate(); requestVersion += 1; window.clearTimeout(tickTimer); window.clearTimeout(pollTimer); channel?.close(); });
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    if (typeof BroadcastChannel === "function") {
      channel = new BroadcastChannel("projmemo-vault-state");
      channel.onmessage = (message) => { if (message.data?.type === "refresh") { invalidate(); void sync(); } };
    }
    invalidate(); poll();
  });
  invalidate();
  tick();
  poll();
})();
