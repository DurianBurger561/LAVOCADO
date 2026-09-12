"use strict";

const ui = {
  inFlight: new Set(),
  timers: [],
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

function showMessage(message, isError = false) {
  const target = element("action-message");
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
  renderTemporal(data.temporal);

  const rescue = data.rescue || {};
  const tile = rescue.tile_index === null || rescue.tile_index === undefined ? "—" : Number(rescue.tile_index) + 1;
  text("rescue-tile", tile);
  text("rescue-pin", String(rescue.pinned_checks_remaining || 0));
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
  } catch (error) {
    showMessage(error instanceof Error ? error.message : "Local request failed.", true);
    await refreshStatus();
  }
}

async function initializeDashboard() {
  element("start-button").addEventListener("click", () => runAction("start_protection"));
  element("stop-button").addEventListener("click", () => runAction("stop_protection"));
  element("test-button").addEventListener("click", () => runAction("test_intervention"));
  element("refresh-history").addEventListener("click", refreshEvents);

  await Promise.all([refreshStatus(), refreshDiagnostics(), refreshEvents()]);
  ui.timers.push(window.setInterval(refreshDiagnostics, 500));
  ui.timers.push(window.setInterval(refreshStatus, 1000));
  ui.timers.push(window.setInterval(refreshEvents, 2000));
}

window.addEventListener("pywebviewready", initializeDashboard, { once: true });
window.addEventListener("beforeunload", () => {
  ui.timers.forEach((timer) => window.clearInterval(timer));
});

renderTemporal([]);
