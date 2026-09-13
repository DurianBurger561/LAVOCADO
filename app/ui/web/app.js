"use strict";

const ui = {
  inFlight: new Set(),
  timers: [],
  canEditRules: false,
  appPickTimer: null,
};

const element = (id) => document.getElementById(id);

function text(id, value) {
  element(id).textContent = value;
}

function formatNumber(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "—";
}

function humanize(value, fallback = "No candidate") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value)
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

const captureBackendNames = {
  windows_dxgi: "Windows DXGI",
  macos_screencapturekit: "macOS ScreenCaptureKit",
  linux_pipewire_portal: "Linux PipeWire Portal",
  linux_xshm: "Linux XShm",
  mss: "MSS",
};

function captureBackendName(backend) {
  if (!backend) {
    return "—";
  }
  return captureBackendNames[backend] || humanize(backend, "Unknown");
}

function captureMode(capture) {
  const backend = capture.active_backend;
  if (!backend) {
    return { label: "Not started", className: "neutral" };
  }
  if (backend === "mss") {
    return {
      label: capture.fallback ? "MSS · Fallback" : "MSS · Active",
      className: capture.fallback ? "capture-fallback" : "capture-healthy",
    };
  }
  return {
    label: `Native · ${captureBackendName(backend)}`,
    className: capture.healthy ? "capture-healthy" : "capture-error",
  };
}

function ruleLabel(action) {
  if (action === "force_block") return "Blocked";
  if (action === "full_bypass") return "Whitelisted";
  return "No rule";
}

function showMessage(message, isError = false) {
  const target = element("action-message");
  target.textContent = message || "";
  target.classList.toggle("error", isError);
}

function showRuleMessage(message, isError = false) {
  const target = element("rules-message");
  target.textContent = message || "";
  target.classList.toggle("error", isError);
}

async function invoke(method, ...args) {
  if (!window.pywebview || !window.pywebview.api) {
    throw new Error("The local dashboard bridge is not ready.");
  }
  return window.pywebview.api[method](...args);
}

function assertResponse(response) {
  if (!response || response.ok !== true) {
    throw new Error(response && response.message ? response.message : "Local request failed.");
  }
  return response;
}

async function guarded(name, task) {
  if (ui.inFlight.has(name)) {
    return;
  }
  ui.inFlight.add(name);
  try {
    await task();
  } catch (error) {
    showMessage(error instanceof Error ? error.message : "Local request failed.", true);
  } finally {
    ui.inFlight.delete(name);
  }
}

function renderStatus(response) {
  const status = response.status || "Stopped";
  const normalized = status.toLowerCase();
  text("protection-state", status);
  element("state-dot").className = `state-dot ${normalized}`;
  element("start-button").disabled = !response.can_start;
  element("stop-button").disabled = !response.can_stop;
  element("test-button").disabled = normalized !== "running";

  if (normalized === "running") {
    text("status-detail", "Monitoring every detected display. Confirmed risk is covered only on the affected screen.");
  } else if (normalized === "stopping") {
    text("status-detail", "Finishing the current local operation and closing protection safely.");
  } else if (normalized === "failed") {
    const code = response.exit_code === null ? "unknown" : response.exit_code;
    text("status-detail", `Protection stopped unexpectedly with exit code ${code}.`);
  } else {
    text("status-detail", "Start monitoring when you are ready. Every connected display is checked locally.");
  }
}

async function refreshStatus() {
  await guarded("status", async () => {
    const response = assertResponse(await invoke("get_status"));
    renderStatus(response);
  });
}

function renderTemporal(values) {
  const history = Array.isArray(values) ? values.slice(-3) : [];
  const padded = Array(Math.max(0, 3 - history.length)).fill(0).concat(history);
  const target = element("temporal-dots");
  target.replaceChildren();
  padded.forEach((value) => {
    const dot = document.createElement("span");
    dot.classList.toggle("hit", Boolean(value));
    target.appendChild(dot);
  });
  const hits = history.filter(Boolean).length;
  target.setAttribute("aria-label", `${hits} candidate frames in the latest 3 checks`);
  text("temporal-count", `${hits} / 3`);
}

function renderDiagnostics(data) {
  text("diag-model", data.model || "NudeNet");
  const contextStatus = humanize(data.context_status, "Unknown");
  text("diag-context-model", `${data.context_model || "Context model"} · ${contextStatus}`);
  text("diag-yolo", humanize(data.yolo_status, "Disabled"));
  text("diag-scan", data.last_scan_ms === null ? "—" : `${formatNumber(data.last_scan_ms, 0)} ms`);
  text("diag-monitor", data.monitor_index === null ? "—" : `Display ${data.monitor_index}`);

  if (data.last_scan_at) {
    const updated = new Date(data.last_scan_at);
    text("diag-updated", Number.isNaN(updated.getTime()) ? data.last_scan_at : updated.toLocaleTimeString());
  } else {
    text("diag-updated", "Waiting for first scan");
  }

  const capture = data.capture || {};
  const mode = captureMode(capture);
  text("capture-mode", mode.label);
  element("capture-mode").className = `signal-tag ${mode.className}`;
  text("capture-preferred", captureBackendName(capture.preferred_backend));
  text("capture-active", captureBackendName(capture.active_backend));
  text("capture-fallback", capture.fallback ? "Yes" : "No");
  text("capture-monitors", String(Math.max(0, Number(capture.monitor_count) || 0)));
  text(
    "capture-frame-age",
    capture.frame_age_ms === null || capture.frame_age_ms === undefined
      ? "—"
      : `${formatNumber(capture.frame_age_ms, 1)} ms`,
  );
  text("capture-reason", capture.fallback_reason || capture.error || "—");
  let captureHealth = "Not started";
  let captureHealthClass = "neutral";
  if (capture.error || (capture.active_backend && !capture.healthy)) {
    captureHealth = "Error";
    captureHealthClass = "capture-error";
  } else if (capture.fallback) {
    captureHealth = "Fallback";
    captureHealthClass = "capture-fallback";
  } else if (capture.active_backend && capture.healthy) {
    captureHealth = "Healthy";
    captureHealthClass = "capture-healthy";
  }
  text("capture-health", captureHealth);
  element("capture-health").className = `signal-tag ${captureHealthClass}`;

  const foreground = data.foreground_context || {};
  const effectivePolicy = foreground.effective_policy || "normal";
  text("foreground-application", foreground.application_available ? "Available" : "Unavailable");
  text("foreground-browser", foreground.is_browser === null || foreground.is_browser === undefined
    ? "—" : foreground.is_browser ? "Yes" : "No");
  text("foreground-website", humanize(foreground.website_state, "Unavailable"));
  text("foreground-app-rule", ruleLabel(foreground.application_rule));
  text("foreground-website-rule", ruleLabel(foreground.website_rule));
  text("foreground-effective", humanize(effectivePolicy, "Normal"));
  text("foreground-policy", humanize(effectivePolicy, "Normal"));
  element("foreground-policy").className = `signal-tag context-policy ${effectivePolicy}`;
  text("foreground-vision-called", foreground.vision_called === false ? "No" : "Yes");

  const nude = data.nudenet || {};
  text("nude-label", humanize(nude.label, "No detection"));
  text("nude-status", humanize(nude.status, "None"));
  element("nude-status").className = `signal-tag ${nude.status || "neutral"}`;
  const threshold = nude.threshold === null || nude.threshold === undefined ? "—" : formatNumber(nude.threshold);
  text("nude-score", `${formatNumber(nude.score)} / ${threshold} threshold`);
  const progress = Math.min(100, Math.max(0, Number(nude.score) * 100 || 0));
  element("nude-progress").style.width = `${progress}%`;

  const context = data.context || {};
  text("context-label", humanize(context.label, "No result"));
  text("context-score", context.score === null || context.score === undefined ? "—" : formatNumber(context.score));
  text("decision-source", humanize(data.decision_source));
  text(
    "decision-classification",
    data.classification
      ? humanize(data.classification, "Clear")
      : "Visual violation only; tile rank cannot block",
  );
  renderTemporal(data.temporal);

  const rescue = data.rescue || {};
  const tile = rescue.tile_index === null || rescue.tile_index === undefined ? "—" : Number(rescue.tile_index) + 1;
  text("rescue-tile", tile);
  text("rescue-pin", String(rescue.pinned_checks_remaining || 0));
  renderFailureExplorer(data);
}

function renderFailureExplorer(data) {
  const foreground = data.foreground_context || {};
  const effectivePolicy = foreground.effective_policy || "normal";
  const protectionState = String(data.protection_state || "").toUpperCase();
  const protect = effectivePolicy === "force_block"
    || protectionState === "BLOCKED"
    || protectionState === "COOLDOWN";
  const nude = data.nudenet || {};
  const evidence = nude.label
    ? `${humanize(nude.label)} ${formatNumber(nude.score)}`
    : humanize(data.classification, "None");
  const temporal = Array.isArray(data.temporal) ? data.temporal : [];
  text("explorer-policy", humanize(effectivePolicy, "Normal"));
  text("explorer-app-rule", ruleLabel(foreground.application_rule));
  text("explorer-website-rule", ruleLabel(foreground.website_rule));
  text("explorer-vision-called", foreground.vision_called === false ? "No" : "Yes");
  text("explorer-evidence", evidence);
  text("explorer-temporal", temporal.length ? temporal.join(" ") : "—");
  text("explorer-final", protect ? "Protect" : "Allow");
  text("explorer-action", protect ? "Protect" : "Allow");
  element("explorer-action").className = `signal-tag context-policy ${protect ? "force_block" : "normal"}`;
}

async function refreshDiagnostics() {
  await guarded("diagnostics", async () => {
    const response = assertResponse(await invoke("get_diagnostics"));
    renderDiagnostics(response.diagnostics || {});
  });
}

function appendCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = value;
  row.appendChild(cell);
}

function renderEvents(response) {
  const events = Array.isArray(response.events) ? response.events : [];
  const body = element("history-body");
  body.replaceChildren();
  text("history-count", String(response.total || 0));
  element("history-empty").hidden = events.length > 0;

  events.forEach((event) => {
    const row = document.createElement("tr");
    const timestamp = new Date(event.occurred_at);
    appendCell(row, Number.isNaN(timestamp.getTime()) ? event.occurred_at : timestamp.toLocaleString());
    appendCell(row, humanize(event.trigger_type, "—"));
    appendCell(row, humanize(event.label, "—"));
    appendCell(row, event.confidence === null ? "—" : formatNumber(event.confidence));
    appendCell(row, String(event.monitor_index));
    appendCell(row, event.intervention_shown ? "Yes" : "No");
    body.appendChild(row);
  });
}

async function refreshEvents() {
  await guarded("events", async () => {
    const response = assertResponse(await invoke("get_events", 50));
    renderEvents(response);
  });
}

async function runAction(method) {
  element("start-button").disabled = true;
  element("stop-button").disabled = true;
  element("test-button").disabled = true;
  try {
    const response = assertResponse(await invoke(method));
    showMessage(response.message || "Done.");
    renderStatus(response);
    await refreshDiagnostics();
    await refreshRules();
  } catch (error) {
    showMessage(error instanceof Error ? error.message : "Local request failed.", true);
    await refreshStatus();
  }
}

const ruleGroups = [
  "blocked_applications",
  "whitelisted_applications",
  "blocked_websites",
  "whitelisted_websites",
];

const whitelistWarnings = {
  whitelisted_applications: [
    "Add application to whitelist?",
    "Whitelisted applications and websites completely bypass visual protection.\n\nUse the whitelist for trusted contexts such as medical, educational, artistic, news, or other non-pornographic use cases that may contain visually explicit content.\n\nVisual protection will be completely disabled while this application is active, unless a higher-priority blacklist rule is matched.\n\nYou are responsible for content displayed in whitelisted contexts.",
  ],
  whitelisted_websites: [
    "Add website to whitelist?",
    "Whitelisted applications and websites completely bypass visual protection.\n\nUse the whitelist for trusted contexts such as medical, educational, artistic, news, or other non-pornographic use cases that may contain visually explicit content.\n\nVisual protection will be completely disabled while this website is the active tab, unless a higher-priority blacklist rule is matched.\n\nYou are responsible for content displayed in whitelisted contexts.",
  ],
};

function confirmRule(title, body) {
  return new Promise((resolve) => {
    const backdrop = element("rule-confirmation");
    const accept = element("rule-confirm-accept");
    const cancel = element("rule-confirm-cancel");
    text("rule-confirm-title", title);
    text("rule-confirm-body", body);
    backdrop.hidden = false;
    accept.focus();

    function finish(accepted) {
      backdrop.hidden = true;
      accept.removeEventListener("click", onAccept);
      cancel.removeEventListener("click", onCancel);
      document.removeEventListener("keydown", onKeydown);
      resolve(accepted);
    }
    function onAccept() { finish(true); }
    function onCancel() { finish(false); }
    function onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      }
    }
    accept.addEventListener("click", onAccept);
    cancel.addEventListener("click", onCancel);
    document.addEventListener("keydown", onKeydown);
  });
}

function renderRules(response) {
  ui.canEditRules = Boolean(response.can_edit);
  text(
    "rules-hint",
    ui.canEditRules
      ? "Changes are stored locally and apply the next time protection starts. Whitelist trusted medical, educational, artistic, or news sources; LAVOCADO does not determine viewing intent."
      : "Stop protection before editing rules. Current rules remain active until it stops.",
  );
  document.querySelectorAll(".rule-form input, .rule-form select, .rule-form button")
    .forEach((control) => { control.disabled = !ui.canEditRules; });

  ruleGroups.forEach((group) => {
    const list = element(`${group.replaceAll("_", "-")}-list`);
    list.replaceChildren();
    const rules = Array.isArray(response.rules?.[group]) ? response.rules[group] : [];
    if (rules.length === 0) {
      const item = document.createElement("li");
      item.className = "rule-empty";
      item.textContent = "No rules yet";
      list.appendChild(item);
    }
    rules.forEach((rule) => {
      const item = document.createElement("li");
      const value = document.createElement("span");
      value.className = "rule-value";
      value.textContent = rule.identifier || rule.domain;
      item.appendChild(value);
      if (rule.match_mode) {
        const mode = document.createElement("span");
        mode.className = "rule-mode";
        mode.textContent = rule.match_mode === "exact_host" ? "Exact host" : "Subdomains";
        item.appendChild(mode);
      }
      if (!rule.enabled) {
        const disabled = document.createElement("span");
        disabled.className = "rule-mode";
        disabled.textContent = "Disabled";
        item.appendChild(disabled);
      }
      const remove = document.createElement("button");
      remove.className = "text-button rule-remove";
      remove.type = "button";
      remove.textContent = "Remove";
      remove.disabled = !ui.canEditRules;
      remove.setAttribute("aria-label", `Remove ${value.textContent}`);
      remove.addEventListener("click", () => removeRule(group, rule));
      item.appendChild(remove);
      list.appendChild(item);
    });
  });
}

async function refreshRules() {
  if (ui.inFlight.has("rules") || ui.inFlight.has("rule-change")) return;
  ui.inFlight.add("rules");
  try {
    renderRules(assertResponse(await invoke("get_rules")));
  } catch (error) {
    showRuleMessage(error instanceof Error ? error.message : "Could not load rules.", true);
  } finally {
    ui.inFlight.delete("rules");
  }
}

async function addRule(form) {
  if (ui.inFlight.has("rule-change") || !ui.canEditRules) return;
  ui.inFlight.add("rule-change");
  const group = form.dataset.ruleGroup;
  const value = form.elements.namedItem("value").value.trim();
  const matchMode = form.elements.namedItem("match_mode")?.value || "exact_host";
  try {
    if (whitelistWarnings[group]) {
      const [title, body] = whitelistWarnings[group];
      if (!await confirmRule(title, body)) return;
    }
    let response = await invoke("add_rule", group, value, matchMode, false);
    if (response?.conflict) {
      if (!await confirmRule("Replace conflicting rule?", response.message)) return;
      response = await invoke("add_rule", group, value, matchMode, true);
    }
    renderRules(assertResponse(response));
    form.reset();
    showRuleMessage(response.message);
  } catch (error) {
    showRuleMessage(error instanceof Error ? error.message : "Could not add rule.", true);
  } finally {
    ui.inFlight.delete("rule-change");
  }
}

async function removeRule(group, rule) {
  if (ui.inFlight.has("rule-change") || !ui.canEditRules) return;
  ui.inFlight.add("rule-change");
  try {
    const response = assertResponse(await invoke(
      "remove_rule", group, rule.identifier || rule.domain, rule.match_mode || "exact_host",
    ));
    renderRules(response);
    showRuleMessage(response.message);
  } catch (error) {
    showRuleMessage(error instanceof Error ? error.message : "Could not remove rule.", true);
  } finally {
    ui.inFlight.delete("rule-change");
  }
}

async function beginAppPick(form) {
  if (!ui.canEditRules || ui.appPickTimer !== null || ui.inFlight.has("app-pick-start")) return;
  ui.inFlight.add("app-pick-start");
  try {
    const response = assertResponse(await invoke("begin_app_pick"));
    if (response.status !== "pending") {
      showRuleMessage("Application selection is unavailable. Enter its identifier manually.", true);
      return;
    }
    showRuleMessage(`Switch to the target application within ${response.delay_seconds} seconds, then return here.`);
    const started = Date.now();
    ui.appPickTimer = window.setInterval(async () => {
      if (ui.inFlight.has("app-pick-result")) return;
      ui.inFlight.add("app-pick-result");
      try {
        const result = assertResponse(await invoke("get_app_pick_result"));
        if (result.status === "pending" && Date.now() - started < 15000) return;
        window.clearInterval(ui.appPickTimer);
        ui.appPickTimer = null;
        if (result.status === "ready" && result.identifier) {
          const input = form.elements.namedItem("value");
          input.value = result.identifier;
          input.focus();
          showRuleMessage("Application selected. Review its identifier, then add the rule.");
        } else {
          showRuleMessage("No stable application identifier was found. You can enter one manually.", true);
        }
      } catch (error) {
        window.clearInterval(ui.appPickTimer);
        ui.appPickTimer = null;
        showRuleMessage(error instanceof Error ? error.message : "Application selection failed.", true);
      } finally {
        ui.inFlight.delete("app-pick-result");
      }
    }, 500);
  } catch (error) {
    showRuleMessage(error instanceof Error ? error.message : "Application selection failed.", true);
  } finally {
    ui.inFlight.delete("app-pick-start");
  }
}

function renderVisionSettings(settings) {
  const detectors = Array.isArray(settings.primary_detectors)
    ? settings.primary_detectors.join(" + ")
    : settings.primary_detector;
  text("vision-primary-detector", humanize(detectors, "Nudenet"));
  const yolo = settings.yolo || {};
  text(
    "vision-yolo",
    yolo.requested
      ? "Optional primary detector · sexual-act + anatomy"
      : "Off unless an existing local YOLO11 model is configured",
  );
  const contextModel = settings.context_model || {};
  text(
    "vision-context-model",
    `${contextModel.name || "Viddexa"} · ranks tiles, cannot block`,
  );
  const mode = settings.detection_mode || {};
  text("vision-detection-mode", mode.label || "Visual violation only");
  const thresholds = settings.thresholds && typeof settings.thresholds === "object"
    ? Object.entries(settings.thresholds)
      .map(([label, score]) => `${humanize(label)} ${formatNumber(score)}`)
      .join(" · ")
    : "";
  text("vision-thresholds", thresholds || "—");
  const tile = settings.tile || {};
  text(
    "vision-tile",
    tile.enabled === false
      ? "Off"
      : `${tile.rows || 2} × ${tile.columns || 2} ranking`,
  );
  const roi = settings.roi || {};
  text(
    "vision-roi",
    `Expand ${formatNumber(roi.expansion, 2)} · margin ${formatNumber(roi.borderline_margin, 2)}`,
  );
  const temporal = settings.temporal || {};
  text(
    "vision-temporal",
    `${temporal.required_hits || 2} / ${temporal.window_size || 3} fresh frames`,
  );
}

async function refreshVisionSettings() {
  if (ui.inFlight.has("vision-settings")) return;
  ui.inFlight.add("vision-settings");
  try {
    renderVisionSettings(assertResponse(await invoke("get_vision_settings")).settings || {});
  } catch (_error) {
    renderVisionSettings({});
  } finally {
    ui.inFlight.delete("vision-settings");
  }
}

async function initializeDashboard() {
  element("start-button").addEventListener("click", () => runAction("start_protection"));
  element("stop-button").addEventListener("click", () => runAction("stop_protection"));
  element("test-button").addEventListener("click", () => runAction("test_intervention"));
  element("refresh-history").addEventListener("click", refreshEvents);
  document.querySelectorAll(".rule-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      addRule(form);
    });
    const picker = form.querySelector(".pick-app");
    if (picker) picker.addEventListener("click", () => beginAppPick(form));
  });

  await Promise.all([
    refreshStatus(),
    refreshDiagnostics(),
    refreshEvents(),
    refreshRules(),
    refreshVisionSettings(),
  ]);
  ui.timers.push(window.setInterval(refreshDiagnostics, 500));
  ui.timers.push(window.setInterval(refreshStatus, 1000));
  ui.timers.push(window.setInterval(refreshEvents, 2000));
  ui.timers.push(window.setInterval(refreshRules, 2000));
}

window.addEventListener("pywebviewready", initializeDashboard, { once: true });
window.addEventListener("beforeunload", () => {
  ui.timers.forEach((timer) => window.clearInterval(timer));
  if (ui.appPickTimer !== null) window.clearInterval(ui.appPickTimer);
});

renderTemporal([]);
