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
  text("home-protection-state", status);
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
  const runtimeState = humanize(data.protection_state, "Not started");
  text("home-runtime-state", runtimeState);
  text("protection-runtime-state", runtimeState);
  text("diag-model", data.model || humanize(data.primary_detector, "NudeNet"));
  const contextStatus = humanize(data.context_status, "Unknown");
  text("diag-context-model", `${data.context_model || "Region ranker"} · ${contextStatus}`);
  text("diag-yolo", humanize(data.yolo_status, "Disabled"));
  text("diag-scan", data.last_scan_ms === null ? "—" : `${formatNumber(data.last_scan_ms, 0)} ms`);
  text("diag-monitor", data.monitor_index === null ? "—" : `Display ${data.monitor_index}`);

  let lastScan = "Waiting for first scan";
  if (data.last_scan_at) {
    const updated = new Date(data.last_scan_at);
    lastScan = Number.isNaN(updated.getTime()) ? data.last_scan_at : updated.toLocaleTimeString();
  }
  text("diag-updated", lastScan);
  text("home-last-scan", lastScan);

  const capture = data.capture || {};
  const mode = captureMode(capture);
  text("capture-mode", mode.label);
  text("home-capture-mode", mode.label);
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
  renderScanPlan(data);

  const rescue = data.rescue || {};
  const tile = rescue.tile_index === null || rescue.tile_index === undefined ? "—" : Number(rescue.tile_index) + 1;
  text("rescue-tile", tile);
  text("rescue-pin", String(rescue.pinned_checks_remaining || 0));
  renderFailureExplorer(data);
}

function renderScanPlan(data) {
  const scan = data.scan || {};
  const mode = scan.mode || "monitoring";
  text("scan-mode", humanize(mode, "Monitoring"));
  element("scan-mode").className = `signal-tag ${mode === "focused" ? "capture-healthy" : "neutral"}`;
  text(
    "scan-total-ms",
    scan.total_ms === null || scan.total_ms === undefined ? "—" : `${formatNumber(scan.total_ms, 0)} ms`,
  );
  text(
    "scan-interval-ms",
    scan.target_interval_ms === null || scan.target_interval_ms === undefined
      ? "—"
      : `${formatNumber(scan.target_interval_ms, 0)} ms`,
  );
  const latencies = data.latencies || {};
  const stages = ["preprocessing_ms", "primary_ms", "supplementary_ms", "viddexa_ms", "decision_ms", "temporal_ms"];
  text(
    "scan-stage-ms",
    stages.every((key) => latencies[key] == null)
      ? "—"
      : stages.map((key) => latencies[key] == null ? "—" : formatNumber(latencies[key], 1)).join(" / ") + " ms",
  );
  const full = data.full || data.nudenet || {};
  text(
    "scan-full",
    full.label
      ? `${humanize(full.status, "None")} · ${humanize(full.label)} ${formatNumber(full.confidence || full.score)}`
      : humanize(full.status, "None"),
  );
  const ranking = ((data.tiles || {}).ranking) || [];
  text(
    "scan-tiles",
    ranking.length
      ? ranking.slice(0, 4).map((item) => `#${Number(item.index) + 1} ${formatNumber(item.priority)}`).join(" · ")
      : "—",
  );
  const track = data.track || {};
  text(
    "scan-track",
    track.active
      ? `${humanize(track.source, "Track")} · ${track.fresh_hits || 0} hits · ${formatNumber(track.evidence)}`
      : "Inactive",
  );
  const shadow = data.shadow || {};
  text(
    "scan-shadow",
    shadow.agreement
      ? `${humanize(shadow.agreement)} · ${formatNumber(shadow.latency_ms, 0)} ms`
      : "Off",
  );
}

function modelStatusLabel(status) {
  const labels = {
    available: "Available",
    missing: "Not downloaded",
    invalid: "Failed verification",
    downloading: "Downloading",
    failed: "Download failed",
    fallback: "Using fallback",
  };
  return labels[status] || humanize(status, "Unknown");
}

function renderModelStatus(models) {
  const list = element("model-status-list");
  if (!list) return;
  list.replaceChildren();
  (Array.isArray(models) ? models : []).forEach((model) => {
    const item = document.createElement("li");
    const textWrap = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = model.label || model.id;
    const detail = document.createElement("span");
    detail.className = "muted";
    const revision = model.revision ? ` · ${String(model.revision).slice(0, 12)}` : "";
    detail.textContent = `${modelStatusLabel(model.status)}${revision}`;
    if (model.fallback) {
      detail.textContent += ` · fallback ${model.fallback}`;
    }
    if (model.error) {
      detail.textContent += ` · ${model.error}`;
    }
    textWrap.append(title, document.createElement("br"), detail);
    item.append(textWrap);
    if (model.status !== "available" && model.status !== "downloading") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button ghost";
      button.textContent = "Download";
      button.dataset.modelId = model.id;
      button.addEventListener("click", () => downloadRequiredModel(model.id));
      item.append(button);
    }
    list.append(item);
  });
}

async function refreshModelStatus() {
  if (ui.inFlight.has("model-status")) return;
  ui.inFlight.add("model-status");
  try {
    const payload = assertResponse(await invoke("get_model_status"));
    renderModelStatus(payload.models || []);
  } catch (_error) {
    renderModelStatus([]);
  } finally {
    ui.inFlight.delete("model-status");
  }
}

async function downloadRequiredModel(modelId) {
  if (ui.inFlight.has("model-download")) return;
  ui.inFlight.add("model-download");
  try {
    const result = assertResponse(await invoke("download_model", modelId));
    showVisionMessage(result.message || "Download started.");
    await refreshModelStatus();
  } catch (error) {
    showVisionMessage(error instanceof Error ? error.message : "Download failed.", true);
  } finally {
    ui.inFlight.delete("model-download");
  }
}

async function downloadAllRequiredModels() {
  if (ui.inFlight.has("model-download-all")) return;
  ui.inFlight.add("model-download-all");
  try {
    const result = assertResponse(await invoke("download_all_models"));
    renderModelStatus(result.models || []);
    showVisionMessage(result.message || "Required model downloads started.");
  } catch (error) {
    showVisionMessage(error instanceof Error ? error.message : "Download failed.", true);
  } finally {
    ui.inFlight.delete("model-download-all");
  }
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
    "Whitelisted applications and websites completely bypass visual protection.\n\nUse the whitelist for trusted contexts such as medical, educational, artistic, news, or other non-pornographic use cases that may contain visually explicit content.\n\nVisual protection will be completely disabled while this application is active, unless a higher-priority blacklist rule is matched.\n\nYou are responsible for content displayed in whitelisted contexts.\n\n白名单中的应用和网站将完全跳过 LAVOCADO 的视觉保护。\n\n如果你需要查看医学、教育、艺术、新闻或其他非色情目的但可能包含裸露或明确人体内容的来源，可以将可靠来源加入白名单。\n\n你将自行负责白名单环境中显示的内容。",
  ],
  whitelisted_websites: [
    "Add website to whitelist?",
    "Whitelisted applications and websites completely bypass visual protection.\n\nUse the whitelist for trusted contexts such as medical, educational, artistic, news, or other non-pornographic use cases that may contain visually explicit content.\n\nVisual protection will be completely disabled while this website is the active tab, unless a higher-priority blacklist rule is matched.\n\nYou are responsible for content displayed in whitelisted contexts.\n\n白名单中的应用和网站将完全跳过 LAVOCADO 的视觉保护。\n\n如果你需要查看医学、教育、艺术、新闻或其他非色情目的但可能包含裸露或明确人体内容的来源，可以将可靠来源加入白名单。\n\n你将自行负责白名单环境中显示的内容。",
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

function setSelectValue(id, value) {
  const target = element(id);
  if (!target || value === undefined || value === null) return;
  target.value = String(value);
}

function renderVisionSettings(settings) {
  const detectors = Array.isArray(settings.primary_detectors)
    ? settings.primary_detectors.join(" + ")
    : settings.primary_detector;
  text("vision-primary-detector", humanize(detectors, "Nudenet"));
  const yolo = settings.yolo || {};
  text(
    "vision-yolo",
    settings.primary_detector === "yolo11_nsfw_small" || yolo.requested
      ? "Required download · primary when selected"
      : "Required download · independent thresholds, NudeNet fallback if missing",
  );
  const contextModel = settings.context_model || {};
  const contextName = contextModel.name || (settings.context && settings.context.model) || "Viddexa";
  text(
    "vision-context-model",
    `${humanize(contextName, "Viddexa")} · ranks tiles, cannot block`,
  );
  const mode = settings.detection_mode || {};
  text("vision-detection-mode", mode.label || "Visual violation only");
  const thresholdTables = settings.thresholds || {};
  const nudenetTable = thresholdTables.nudenet_640m || {};
  const thresholds = typeof nudenetTable === "object"
    ? Object.entries(nudenetTable)
      .map(([label, pair]) => {
        const strong = pair && typeof pair === "object" ? pair.strong : pair;
        return `${humanize(label)} ${formatNumber(strong)}`;
      })
      .join(" · ")
    : "";
  text("vision-thresholds", thresholds || "—");
  const tile = settings.tile || settings.tiles || {};
  text(
    "vision-tile",
    tile.enabled === false
      ? "Off"
      : `${tile.rows || 2} × ${tile.columns || 2} overlap ${Math.round((tile.overlap || 0.15) * 100)}%`,
  );
  const roi = settings.roi || {};
  const expansion = roi.expansion || (settings.recheck && settings.recheck.crop_expansion);
  text(
    "vision-roi",
    `Expand ${formatNumber(expansion, 2)} · margin ${formatNumber(roi.borderline_margin, 2)}`,
  );
  const temporal = settings.temporal || {};
  text(
    "vision-temporal",
    `${temporal.required_hits || temporal.min_fresh_hits || 2} / ${temporal.window_size || 3} fresh frames`,
  );

  const schema = settings.schema || settings;
  const detector = schema.detector || {};
  const context = schema.context || {};
  const tiles = schema.tiles || tile;
  const scan = schema.scan || settings.scan || {};
  const recheck = schema.recheck || {};
  const shadow = schema.shadow || {};
  setSelectValue("vision-primary-select", detector.primary || settings.primary_detector);
  setSelectValue("vision-context-select", context.model || contextName);
  setSelectValue("vision-preset-select", settings.preset || schema.preset || "balanced");
  setSelectValue("vision-tile-enabled-select", tiles.enabled === false ? "false" : "true");
  const interval = Number(scan.normal_interval_ms || 750);
  const speed = interval <= 550 ? "fast" : interval >= 900 ? "slow" : "balanced";
  setSelectValue("vision-scan-speed-select", speed);
  setSelectValue("vision-grid-select", `${tiles.rows || 2}x${tiles.columns || 2}`);
  setSelectValue("vision-full-input-select", detector.full_input_size || 640);
  setSelectValue("vision-tile-input-select", detector.tile_input_size || 640);
  setSelectValue("vision-overlap-select", Math.round((tiles.overlap || 0.15) * 100));
  setSelectValue("vision-checks-select", tiles.checks_per_scan || 1);
  setSelectValue("vision-max-skip-select", tiles.max_skip || 3);
  setSelectValue("vision-crop-select", recheck.crop_expansion || 1.75);
  setSelectValue("vision-shadow-select", shadow.enabled ? "true" : "false");
  setSelectValue("vision-recheck-select", recheck.enabled === false ? "false" : "true");
  setSelectValue("vision-proposal-select", recheck.proposal_margin || 0.10);
  setSelectValue("vision-adaptive-select", scan.adaptive === false ? "false" : "true");
  setSelectValue("vision-change-select", scan.change_sensitivity || 0.01);
  setSelectValue("vision-active-monitor-select", scan.active_monitor_priority === false ? "false" : "true");
  const temporalSchema = schema.temporal || settings.temporal || {};
  setSelectValue("vision-confirmation-select", temporalSchema.confirmation || "boolean");
  setSelectValue("vision-fresh-hits-select", temporalSchema.min_fresh_hits || temporalSchema.required_hits || 2);
  setSelectValue("vision-evidence-select", temporalSchema.evidence_threshold || 2.5);
  setSelectValue("vision-decay-select", temporalSchema.decay || 0.5);
  renderThresholdTable(thresholdTables);
}

function visionFormPayload() {
  const grid = element("vision-grid-select").value.split("x");
  const speed = element("vision-scan-speed-select").value;
  const intervals = { slow: [1000, 250], balanced: [750, 150], fast: [500, 100] };
  const [normalMs, candidateMs] = intervals[speed] || intervals.balanced;
  return {
    preset: element("vision-preset-select").value,
    detector: {
      primary: element("vision-primary-select").value,
      full_input_size: Number(element("vision-full-input-select").value),
      tile_input_size: Number(element("vision-tile-input-select").value),
    },
    context: { model: element("vision-context-select").value },
    tiles: {
      enabled: element("vision-tile-enabled-select").value === "true",
      rows: Number(grid[0] || 2),
      columns: Number(grid[1] || 2),
      overlap: Number(element("vision-overlap-select").value) / 100,
      checks_per_scan: Number(element("vision-checks-select").value),
      max_skip: Number(element("vision-max-skip-select").value),
    },
    recheck: {
      enabled: element("vision-recheck-select").value === "true",
      crop_expansion: Number(element("vision-crop-select").value),
      proposal_margin: Number(element("vision-proposal-select").value),
    },
    scan: {
      normal_interval_ms: normalMs,
      candidate_interval_ms: candidateMs,
      adaptive: element("vision-adaptive-select").value === "true",
      change_sensitivity: Number(element("vision-change-select").value),
      active_monitor_priority: element("vision-active-monitor-select").value === "true",
    },
    temporal: {
      confirmation: element("vision-confirmation-select").value,
      min_fresh_hits: Number(element("vision-fresh-hits-select").value),
      evidence_threshold: Number(element("vision-evidence-select").value),
      decay: Number(element("vision-decay-select").value),
    },
    shadow: { enabled: element("vision-shadow-select").value === "true" },
    thresholds: collectThresholdTables(),
  };
}

function thresholdSteps() {
  return [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75];
}

function renderThresholdTable(tables) {
  const root = element("vision-threshold-table");
  if (!root) return;
  root.replaceChildren();
  const groups = [
    ["nudenet_640m", "NudeNet 640m", tables.nudenet_640m || {}],
    ["yolo11_nsfw_small", "YOLO11 NSFW Small", tables.yolo11_nsfw_small || {}],
  ];
  groups.forEach(([model, title, rows]) => {
    const heading = document.createElement("p");
    heading.className = "signal-name";
    heading.textContent = title;
    root.append(heading);
    Object.entries(rows).forEach(([label, pair]) => {
      const row = document.createElement("div");
      row.className = "vision-threshold-row";
      const name = document.createElement("span");
      name.className = "muted";
      name.textContent = humanize(label);
      row.append(
        name,
        thresholdSelect(model, label, "proposal", pair && pair.proposal),
        thresholdSelect(model, label, "strong", pair && pair.strong),
      );
      root.append(row);
    });
  });
}

function thresholdSelect(model, label, kind, value) {
  const wrap = document.createElement("label");
  wrap.textContent = kind === "proposal" ? "Proposal" : "Strong";
  const select = document.createElement("select");
  select.dataset.thresholdModel = model;
  select.dataset.thresholdLabel = label;
  select.dataset.thresholdKind = kind;
  thresholdSteps().forEach((step) => {
    const option = document.createElement("option");
    option.value = step.toFixed(2);
    option.textContent = step.toFixed(2);
    select.append(option);
  });
  if (value !== undefined && value !== null) select.value = Number(value).toFixed(2);
  wrap.append(select);
  return wrap;
}

function collectThresholdTables() {
  const tables = { nudenet_640m: {}, yolo11_nsfw_small: {} };
  document.querySelectorAll("[data-threshold-model]").forEach((node) => {
    const model = node.dataset.thresholdModel;
    const label = node.dataset.thresholdLabel;
    const kind = node.dataset.thresholdKind;
    if (!tables[model]) tables[model] = {};
    if (!tables[model][label]) tables[model][label] = {};
    tables[model][label][kind] = Number(node.value);
  });
  return tables;
}

function showVisionMessage(message, isError = false) {
  const target = element("vision-settings-message");
  if (!target) return;
  target.textContent = message || "";
  target.classList.toggle("error", isError);
}

async function saveVisionSettings(event) {
  event.preventDefault();
  if (ui.inFlight.has("vision-save")) return;
  ui.inFlight.add("vision-save");
  try {
    const result = assertResponse(await invoke("save_vision_settings", visionFormPayload()));
    renderVisionSettings(result.settings || {});
    showVisionMessage(result.message || "Settings saved.");
    refreshStatus();
  } catch (error) {
    showVisionMessage(error instanceof Error ? error.message : "Could not save settings.", true);
  } finally {
    ui.inFlight.delete("vision-save");
  }
}

async function resetVisionSettings() {
  if (ui.inFlight.has("vision-reset")) return;
  ui.inFlight.add("vision-reset");
  try {
    const result = assertResponse(await invoke("reset_vision_settings"));
    renderVisionSettings(result.settings || {});
    showVisionMessage(result.message || "Experimental defaults restored.");
  } catch (error) {
    showVisionMessage(error instanceof Error ? error.message : "Could not reset settings.", true);
  } finally {
    ui.inFlight.delete("vision-reset");
  }
}

async function applyVisionPreset() {
  if (ui.inFlight.has("vision-preset")) return;
  ui.inFlight.add("vision-preset");
  try {
    const result = assertResponse(
      await invoke("apply_vision_preset", element("vision-preset-select").value),
    );
    renderVisionSettings(result.settings || {});
    showVisionMessage(result.message || "Preset applied.");
  } catch (error) {
    showVisionMessage(error instanceof Error ? error.message : "Could not apply preset.", true);
  } finally {
    ui.inFlight.delete("vision-preset");
  }
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

function setAppView(view) {
  const known = new Set(["home", "protection", "history", "settings"]);
  if (!known.has(view)) {
    return;
  }
  document.querySelectorAll("#app-nav .nav-button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === view);
  });
  document.querySelectorAll(".home-overview").forEach((node) => {
    node.hidden = view !== "home";
  });
  document.querySelectorAll(".hero").forEach((node) => {
    node.hidden = view !== "protection";
  });
  document.querySelectorAll(".dashboard-grid").forEach((node) => {
    node.hidden = view !== "protection";
  });
  document.querySelectorAll(".history").forEach((node) => {
    node.hidden = view !== "history";
  });
  document.querySelectorAll(".rules, .vision-settings").forEach((node) => {
    node.hidden = view !== "settings";
  });
}

function initializeDashboard() {
  element("start-button").addEventListener("click", () => runAction("start_protection"));
  element("stop-button").addEventListener("click", () => runAction("stop_protection"));
  element("test-button").addEventListener("click", () => runAction("test_intervention"));
  element("refresh-history").addEventListener("click", refreshEvents);
  const visionForm = element("vision-settings-form");
  if (visionForm) visionForm.addEventListener("submit", saveVisionSettings);
  const resetButton = element("vision-reset-button");
  if (resetButton) resetButton.addEventListener("click", resetVisionSettings);
  const downloadAll = element("vision-download-all");
  if (downloadAll) downloadAll.addEventListener("click", downloadAllRequiredModels);
  const presetSelect = element("vision-preset-select");
  if (presetSelect) presetSelect.addEventListener("change", applyVisionPreset);
  element("open-protection-button").addEventListener("click", () => {
    document.querySelector('#app-nav [data-view="protection"]').click();
  });
  document.querySelectorAll(".rule-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      addRule(form);
    });
    const picker = form.querySelector(".pick-app");
    if (picker) picker.addEventListener("click", () => beginAppPick(form));
  });

  if (!document.getElementById("benchmark-lab")) {
    document.querySelectorAll("#app-nav .nav-button").forEach((button) => {
      button.addEventListener("click", () => setAppView(button.dataset.view));
    });
    setAppView("home");
  }

  void Promise.allSettled([
    refreshStatus(),
    refreshDiagnostics(),
    refreshEvents(),
    refreshRules(),
    refreshVisionSettings(),
    refreshModelStatus(),
  ]);
  ui.timers.push(window.setInterval(refreshDiagnostics, 500));
  ui.timers.push(window.setInterval(refreshModelStatus, 4000));
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
