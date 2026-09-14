"use strict";

const lab = {
  view: "protection",
  tab: "dataset",
  samples: [],
  index: 0,
  tags: [],
  selected: new Set(),
  grid: false,
  configs: [],
  progressTimer: null,
  datasetPath: "",
  toolRunId: "",
  toolRuns: [],
};

const labEl = (id) => document.getElementById(id);

function labText(id, value) {
  const node = labEl(id);
  if (node) node.textContent = value;
}

function labMessage(message, isError = false) {
  const target = labEl("lab-message");
  if (!target) return;
  target.textContent = message || "";
  target.classList.toggle("error", isError);
}

async function labInvoke(method, ...args) {
  if (!window.pywebview || !window.pywebview.api) {
    throw new Error("The local dashboard bridge is not ready.");
  }
  return window.pywebview.api[method](...args);
}

function labAssert(response) {
  if (!response || response.ok !== true) {
    throw new Error(response && response.message ? response.message : "Lab request failed.");
  }
  return response;
}

function percent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function setView(view) {
  lab.view = view;
  const developerTool = view === "developer" || view === "diagnostics";
  document.querySelectorAll("#app-nav .nav-button").forEach((button) => {
    const target = button.dataset.view;
    const active = target === view || (developerTool && target === "developer");
    button.classList.toggle("is-active", active);
  });
  const subnav = document.getElementById("developer-subnav");
  if (subnav) {
    subnav.hidden = !developerTool;
    subnav.querySelectorAll(".nav-button").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.view === view);
    });
  }
  const labPanel = labEl("benchmark-lab");
  if (labPanel) labPanel.hidden = view !== "developer";
  document.querySelectorAll(".hero").forEach((node) => {
    node.hidden = !(view === "home" || view === "protection");
  });
  document.querySelectorAll(".dashboard-grid").forEach((node) => {
    node.hidden = !(view === "home" || view === "diagnostics");
  });
  document.querySelectorAll(".history").forEach((node) => {
    node.hidden = view !== "history";
  });
  document.querySelectorAll(".rules, .vision-settings").forEach((node) => {
    node.hidden = view !== "settings";
  });
}

function setLabTab(tab) {
  lab.tab = tab;
  document.querySelectorAll(".lab-tab").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.labTab === tab);
  });
  document.querySelectorAll(".lab-pane").forEach((pane) => {
    pane.classList.toggle("is-active", pane.dataset.labPane === tab);
  });
}

function checkedValues(name) {
  return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map((node) => node.value);
}

function selectValue(id, fallback) {
  const node = labEl(id);
  return node && node.value !== "" ? node.value : fallback;
}

function configPayload() {
  const target = document.querySelector('input[name="lab-target"]:checked');
  return {
    benchmark_target: target ? target.value : "full_protection_pipeline",
    detectors: checkedValues("lab-detector"),
    context_models: checkedValues("lab-context"),
    full_input_sizes: checkedValues("lab-full-size").map(Number),
    tile_modes: checkedValues("lab-tile-mode"),
    overlaps: checkedValues("lab-overlap").map(Number),
    tile_input_sizes: checkedValues("lab-tile-size").map(Number),
    threshold_profile: selectValue("lab-threshold-profile", "current"),
    proposal_margin: Number(selectValue("lab-proposal-margin", "0.10")),
    crop_expansion: Number(selectValue("lab-crop-expansion", "1.75")),
    checks_per_scan: Number(selectValue("lab-checks-per-scan", "1")),
    max_skip: Number(selectValue("lab-max-skip", "3")),
    tile_ranking: selectValue("lab-tile-ranking", "true") === "true",
    confirmation: selectValue("lab-confirmation", "boolean"),
    window_size: Number(selectValue("lab-window-size", "3")),
    min_fresh_hits: Number(selectValue("lab-fresh-hits", "2")),
    evidence_threshold: Number(selectValue("lab-evidence-threshold", "2.5")),
    decay: Number(selectValue("lab-decay", "0.5")),
    strong_values: checkedValues("lab-sweep-strong").map(Number),
    proposal_values: checkedValues("lab-sweep-proposal").map(Number),
  };
}

function renderCounts(counts) {
  const target = labEl("lab-dataset-counts");
  if (!target || !counts) return;
  target.innerHTML = [
    ["Total", counts.total],
    ["Labelled", counts.labelled],
    ["Unlabelled", counts.unlabelled],
    ["Block", counts.block],
    ["Allow", counts.allow],
    ["Excluded", counts.excluded],
  ].map(([label, value]) => `<div><dt>${label}</dt><dd>${value ?? 0}</dd></div>`).join("");
}

function renderDatasets(datasets) {
  const list = labEl("lab-dataset-list");
  if (!list) return;
  const currentPath = lab.datasetPath || "";
  list.innerHTML = "";
  (datasets || []).forEach((item) => {
    const row = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-button";
    const active = currentPath && item.path === currentPath;
    button.textContent = `${item.name} · ${item.total || 0} samples${active ? " · open" : ""}`;
    button.addEventListener("click", () => openDataset(item.path));
    row.appendChild(button);
    list.appendChild(row);
  });
}

function renderTagFilters() {
  const filter = labEl("lab-filter-tag");
  const fail = labEl("lab-fail-tag");
  const boxes = labEl("lab-tag-boxes");
  if (filter) {
    filter.innerHTML = '<option value="">Any tag</option>';
    lab.tags.forEach((tag) => {
      const option = document.createElement("option");
      option.value = tag.id;
      option.textContent = tag.label;
      filter.appendChild(option);
    });
  }
  if (fail) {
    fail.innerHTML = '<option value="">Any tag</option>';
    lab.tags.forEach((tag) => {
      const option = document.createElement("option");
      option.value = tag.id;
      option.textContent = tag.label;
      fail.appendChild(option);
    });
  }
  if (boxes) {
    boxes.innerHTML = "";
    lab.tags.forEach((tag) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = tag.id;
      input.dataset.tag = tag.id;
      label.appendChild(input);
      label.append(` ${tag.label}`);
      boxes.appendChild(label);
    });
  }
}

function currentSample() {
  return lab.samples[lab.index] || null;
}

async function showCurrentSample() {
  const sample = currentSample();
  labText("lab-annotate-index", sample ? `Image ${lab.index + 1} / ${lab.samples.length}` : "No samples");
  const image = labEl("lab-preview");
  const hint = labEl("lab-unlabelled-hint");
  if (!sample) {
    if (image) image.hidden = true;
    return;
  }
  const response = labAssert(await labInvoke("lab_preview", sample.id));
  if (image) {
    image.src = response.preview || "";
    image.hidden = !response.preview;
  }
  if (hint) {
    hint.hidden = !(response.sample && response.sample.expected == null);
  }
  const exclude = labEl("lab-exclude");
  if (exclude) exclude.checked = Boolean(response.sample && response.sample.excluded);
  const expectedVisual = labEl("lab-expected-visual");
  if (expectedVisual) expectedVisual.value = response.sample.expected_visual || "unlabelled";
  document.querySelectorAll("#lab-tag-boxes input").forEach((input) => {
    input.checked = Boolean(response.sample && (response.sample.tags || []).includes(input.value));
  });
}

async function refreshSamples() {
  const status = labEl("lab-filter-status").value;
  const tag = labEl("lab-filter-tag").value;
  const tags = tag ? [tag] : [];
  const response = labAssert(await labInvoke("lab_samples", status, tags));
  lab.samples = response.samples || [];
  lab.index = Math.min(lab.index, Math.max(0, lab.samples.length - 1));
  renderCounts(response.counts);
  if (lab.grid) await renderGrid();
  else await showCurrentSample();
}

async function renderGrid() {
  const grid = labEl("lab-grid");
  if (!grid) return;
  grid.innerHTML = "";
  for (const sample of lab.samples.slice(0, 60)) {
    const item = document.createElement("div");
    item.className = "lab-grid-item";
    if (lab.selected.has(sample.id)) item.classList.add("is-selected");
    item.dataset.id = sample.id;
    const caption = document.createElement("p");
    caption.className = "muted";
    caption.textContent = sample.expected || "Unlabelled";
    item.appendChild(caption);
    item.addEventListener("click", () => {
      if (lab.selected.has(sample.id)) lab.selected.delete(sample.id);
      else lab.selected.add(sample.id);
      item.classList.toggle("is-selected");
    });
    grid.appendChild(item);
    labInvoke("lab_preview", sample.id).then((response) => {
      if (!response || !response.preview) return;
      const img = document.createElement("img");
      img.alt = sample.id;
      img.src = response.preview;
      item.prepend(img);
    }).catch(() => {});
  }
}

async function annotateCurrent(payload) {
  const sample = currentSample();
  if (!sample) return;
  const tags = Array.from(document.querySelectorAll("#lab-tag-boxes input:checked")).map((node) => node.value);
  labAssert(await labInvoke("lab_annotate", sample.id, payload.expected ?? sample.expected, payload.excluded ?? sample.excluded, payload.tags || tags, payload.expected_visual || selectValue("lab-expected-visual", "unlabelled")));
  await refreshSamples();
}

async function refreshDatasets() {
  const response = labAssert(await labInvoke("lab_list_datasets"));
  renderDatasets(response.datasets);
}

async function applyOpenedDataset(response, action = "Opened") {
  const dataset = response.dataset;
  lab.datasetPath = dataset.path;
  labMessage(`${action} ${dataset.name}`);
  renderCounts(dataset);
  lab.samples = dataset.samples || [];
  lab.index = 0;
  await showCurrentSample();
  await refreshDatasets();
}

async function openDataset(path) {
  const response = labAssert(await labInvoke("lab_open_dataset", path));
  await applyOpenedDataset(response);
}

async function refreshConfigs() {
  const payload = configPayload();
  const sweep = labEl("lab-threshold-sweep");
  if (sweep) sweep.hidden = ["detector_only", "context_policy"].includes(payload.benchmark_target);
  const response = labAssert(await labInvoke("lab_expand_configs", payload));
  lab.configs = response.configs || [];
  labText("lab-config-count", `${response.count} configurations`);
}

function renderSummary(run) {
  const box = labEl("lab-summary");
  if (!box) return;
  const summaries = Object.values((run && run.summaries) || {});
  const summary = summaries[0] || {};
  const detectorOnly = summary.target === "detector_only";
  const contextOnly = summary.target === "context_policy";
  const matrix = labEl("lab-matrix");
  const detectorNote = labEl("lab-detector-note");
  const detectorList = labEl("lab-detector-list");
  if (matrix) matrix.hidden = detectorOnly || contextOnly;
  if (detectorNote) detectorNote.hidden = !detectorOnly;
  if (detectorList) detectorList.hidden = !detectorOnly;
  const latency = (value) => (value == null ? "—" : `${Number(value).toFixed(0)} ms`);
  const items = contextOnly
    ? [
        ["Samples", summary.sample_count ?? 0],
        ["Labelled policies", summary.labelled_count ?? 0],
        ["Correct", summary.correct ?? 0],
        ["Incorrect", summary.incorrect ?? 0],
        ["Policy accuracy", percent(summary.accuracy)],
        ["Mean latency", latency(summary.mean_latency_ms)],
      ]
    : detectorOnly
    ? [
        ["Samples", summary.sample_count ?? 0],
        ["Detections", summary.detection_count ?? 0],
        ["Mean latency", latency(summary.mean_latency_ms)],
        ["p95 latency", latency(summary.p95_latency_ms)],
      ]
    : [
        ["Accuracy", percent(summary.accuracy)],
        ["Failure rate", percent(summary.failure_rate)],
        ["Recall", percent(summary.recall)],
        ["Precision", percent(summary.precision)],
        ["FNR", percent(summary.fnr)],
        ["FPR", percent(summary.fpr)],
        ["Mean latency", latency(summary.mean_latency_ms)],
        ["p95 latency", latency(summary.p95_latency_ms)],
      ];
  const ranking = summary.ranking || {};
  if (!detectorOnly && !contextOnly && ranking.eligible_samples) {
    items.push(
      ["Top-1 relevant tile", percent(ranking.top1_relevant_tile_rate)],
      ["Top-2 relevant tile", percent(ranking.top2_relevant_tile_rate)],
      ["Context latency", latency(ranking.mean_context_latency_ms)],
    );
  }
  box.innerHTML = items.map(([label, value]) => `<div><span class="muted">${label}</span><strong>${value}</strong></div>`).join("");
  if (!detectorOnly && !contextOnly) {
    labText("lab-tp", summary.tp ?? "—");
    labText("lab-tn", summary.tn ?? "—");
    labText("lab-fp", summary.fp ?? "—");
    labText("lab-fn", summary.fn ?? "—");
  }
  if (detectorList) {
    detectorList.innerHTML = (summary.detections || []).slice(0, 80).map((item) => {
      const boxText = Array.isArray(item.box) ? item.box.map((value) => Number(value).toFixed(0)).join(", ") : "—";
      const score = item.confidence == null ? "—" : Number(item.confidence).toFixed(2);
      return `<div class="lab-fail-row">${item.label || "detection"} · ${score} · bbox [${boxText}]</div>`;
    }).join("");
  }
  const tagBox = labEl("lab-tag-metrics");
  if (tagBox) {
    if (detectorOnly || contextOnly) {
      tagBox.innerHTML = "";
      return;
    }
    const tags = summary.tag_metrics || {};
    tagBox.innerHTML = Object.entries(tags).filter(([key]) => key !== "non_pornographic_purpose_allow_rate").slice(0, 12).map(([key, value]) => {
      const label = value.label || key;
      const recall = percent(value.recall);
      const allow = percent(value.allow_rate);
      return `<p>${label}: recall ${recall} · allow rate ${allow}</p>`;
    }).join("");
    if (tags.non_pornographic_purpose_allow_rate != null) {
      tagBox.innerHTML += `<p>Non-pornographic-purpose Allow Rate: ${percent(tags.non_pornographic_purpose_allow_rate)}</p>`;
    }
  }
}

async function refreshResults() {
  const response = labAssert(await labInvoke("lab_results"));
  renderSummary(response.run);
}

async function refreshFailures() {
  const kind = labEl("lab-fail-kind").value;
  const tag = labEl("lab-fail-tag").value || null;
  const response = labAssert(await labInvoke("lab_failures", kind, tag, null));
  const box = labEl("lab-failures");
  box.innerHTML = "";
  (response.rows || []).slice(0, 80).forEach((row) => {
    const item = document.createElement("div");
    item.className = "lab-fail-row";
    if (row.target === "detector_only") {
      const detections = (row.raw && row.raw.detections) || [];
      const top = detections[0] || {};
      const score = top.score == null ? "—" : Number(top.score).toFixed(2);
      item.textContent = `${row.sample_id} · ${detections.length} detections · ${top.class || "none"} ${score}`;
    } else {
      item.textContent = `${row.sample_id} · expected ${row.expected || "unlabelled"} · predicted ${row.predicted || "—"} · ${row.outcome || ""}`;
    }
    item.addEventListener("click", () => {
      document.querySelectorAll(".lab-fail-row").forEach((node) => node.classList.remove("is-active"));
      item.classList.add("is-active");
      const detail = labEl("lab-failure-detail");
      const decision = row.decision_summary || {};
      const detector = row.detector_summary || {};
      const context = row.context_summary || {};
      const temporal = row.temporal_summary || {};
      detail.innerHTML = `
        <p><strong>Sample ${row.sample_id}</strong></p>
        <p>Expected ${row.expected || "Unlabelled"} · Predicted ${row.predicted || "—"}</p>
        <p>Tags: ${(row.tags || []).join(", ") || "—"}</p>
        <p>Detector: ${detector.best_label || "none"} ${detector.best_confidence == null ? "" : detector.best_confidence}</p>
        <p>Decision: ${decision.source || "—"} · ${decision.classification || "—"} · ${decision.label || ""}</p>
        <p>Context: ${context.policy_action || "not evaluated"} · Vision ${row.vision_called ? "called" : "skipped"}</p>
        <p>Temporal: ${temporal.history ? temporal.history.join(", ") : "n/a"} · Confirmed ${temporal.confirmed ? "yes" : "no"}</p>
        <p>Latency: ${row.total_ms == null ? "—" : `${Number(row.total_ms).toFixed(1)} ms`}</p>
        <p>Ranking: ${row.ranking && row.ranking.eligible ? `Top-1 ${row.ranking.top1} · Top-2 ${row.ranking.top2} · context ${row.ranking.context_latency_ms == null ? "—" : `${Number(row.ranking.context_latency_ms).toFixed(1)} ms`}` : "n/a"}</p>
      `;
    });
    box.appendChild(item);
  });
}

async function refreshCompare() {
  const key = labEl("lab-sort-key").value;
  const response = labAssert(await labInvoke("lab_compare", key));
  const body = labEl("lab-compare-body");
  const highlights = (response.comparison && response.comparison.highlights) || {};
  body.innerHTML = "";
  (response.comparison.rows || []).forEach((row) => {
    const tr = document.createElement("tr");
    const marks = [];
    if (highlights.highest_recall === row.config_id) marks.push("Highest Recall");
    if (highlights.lowest_fnr === row.config_id) marks.push("Lowest FNR");
    if (highlights.lowest_fpr === row.config_id) marks.push("Lowest FPR");
    if (highlights.lowest_latency === row.config_id) marks.push("Lowest Latency");
    tr.innerHTML = `
      <td>${row.label || row.config_id}${marks.length ? `<br><span class="muted">${marks.join(" · ")}</span>` : ""}</td>
      <td>${percent(row.recall)}</td>
      <td>${percent(row.fnr)}</td>
      <td>${percent(row.fpr)}</td>
      <td>${percent(row.precision)}</td>
      <td>${percent(row.accuracy)}</td>
      <td>${row.p95_latency_ms == null ? "—" : `${Number(row.p95_latency_ms).toFixed(0)} ms`}</td>
      <td>${percent(row.top1_relevant_tile_rate)}</td>
      <td>${percent(row.top2_relevant_tile_rate)}</td>
      <td>${row.mean_context_latency_ms == null ? "—" : `${Number(row.mean_context_latency_ms).toFixed(0)} ms`}</td>
    `;
    body.appendChild(tr);
  });
}

async function pollProgress() {
  const response = await labInvoke("lab_progress");
  if (!response || !response.ok) return;
  const progress = response.progress || {};
  labText(
    "lab-run-status",
    `${progress.status || "idle"} · config ${progress.config_index || 0} / ${progress.config_count || 0} · sample ${progress.sample_index || 0} / ${progress.sample_count || 0} · ${progress.current || ""}`,
  );
  if (progress.status === "completed" || progress.status === "cancelled") {
    await refreshResults();
    await refreshFailures();
    await refreshCompare();
  }
}

async function pollToolProgress() {
  const response = await labInvoke("lab_tool_progress");
  if (!response || !response.ok || !response.job) return;
  const job = response.job;
  const progress = job.progress || {};
  labText("lab-tool-status", `${job.kind}: ${job.status}${progress.completed != null ? ` · ${progress.completed}/${progress.total}` : ""}${progress.backend ? ` · ${progress.backend}` : ""}${progress.active_backend ? ` · ${progress.active_backend}` : ""}${progress.elapsed_seconds != null ? ` · ${progress.elapsed_seconds}s` : ""}${progress.frames != null ? ` · ${progress.frames} frames` : ""}`);
  if (job.record) {
    lab.toolRunId = job.record.id;
    labText("lab-tool-result", JSON.stringify(job.record, null, 2));
    if (!lab.toolRuns.some((item) => item.id === job.record.id)) refreshToolHistory().catch(() => {});
  }
}

async function refreshToolHistory() {
  const response = labAssert(await labInvoke("lab_tool_history"));
  lab.toolRuns = response.runs || [];
  const container = labEl("lab-tool-history");
  container.replaceChildren();
  for (const record of lab.toolRuns) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button ghost";
    button.textContent = `${record.created_at || ""} · ${record.kind || "tool"} · ${record.status || ""}`;
    button.addEventListener("click", () => {
      lab.toolRunId = record.id;
      labText("lab-tool-result", JSON.stringify(record, null, 2));
    });
    container.appendChild(button);
  }
}

async function startTool(kind, options) {
  const response = labAssert(await labInvoke("lab_start_tool", kind, options));
  lab.toolRunId = response.job_id;
  labText("lab-tool-result", "");
  labMessage(response.message);
  await pollToolProgress();
}

function initializeLab() {
  const nav = document.getElementById("app-nav");
  if (!nav) return;
  document.querySelectorAll("#app-nav .nav-button, #developer-subnav .nav-button").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  document.querySelectorAll(".lab-tab").forEach((button) => {
    button.addEventListener("click", () => setLabTab(button.dataset.labTab));
  });
  labEl("lab-create-dataset").addEventListener("click", async () => {
    try {
      const name = labEl("lab-dataset-name").value;
      const response = labAssert(await labInvoke("lab_create_dataset", name));
      await applyOpenedDataset(response, "Created");
    } catch (error) {
      labMessage(error.message, true);
    }
  });
  labEl("lab-open-dataset").addEventListener("click", async () => {
    try {
      const response = labAssert(await labInvoke("lab_open_dataset", null));
      await applyOpenedDataset(response);
    } catch (error) {
      labMessage(error.message, true);
    }
  });
  labEl("lab-open-dataset-folder").addEventListener("click", async () => {
    try {
      const response = labAssert(await labInvoke("lab_open_dataset_folder", null));
      await applyOpenedDataset(response);
    } catch (error) {
      labMessage(error.message, true);
    }
  });
  labEl("lab-refresh-datasets").addEventListener("click", () => refreshDatasets().catch((error) => labMessage(error.message, true)));
  labEl("lab-import-images").addEventListener("click", async () => {
    try {
      const mode = labEl("lab-import-mode").value;
      const response = labAssert(await labInvoke("lab_import_images", null, mode, null));
      labMessage(`Imported ${response.import.added} images`);
      renderCounts(response.dataset);
      await refreshSamples();
    } catch (error) {
      labMessage(error.message, true);
    }
  });
  labEl("lab-import-folder").addEventListener("click", async () => {
    try {
      const mode = labEl("lab-import-mode").value;
      const response = labAssert(await labInvoke("lab_import_folder", null, mode));
      labMessage(`Imported ${response.import.added} images`);
      renderCounts(response.dataset);
      await refreshSamples();
    } catch (error) {
      labMessage(error.message, true);
    }
  });
  labEl("lab-filter-status").addEventListener("change", () => refreshSamples().catch((error) => labMessage(error.message, true)));
  labEl("lab-filter-tag").addEventListener("change", () => refreshSamples().catch((error) => labMessage(error.message, true)));
  labEl("lab-mark-block").addEventListener("click", () => annotateCurrent({ expected: "block" }).catch((error) => labMessage(error.message, true)));
  labEl("lab-mark-allow").addEventListener("click", () => annotateCurrent({ expected: "allow" }).catch((error) => labMessage(error.message, true)));
  labEl("lab-exclude").addEventListener("change", (event) => annotateCurrent({ excluded: event.target.checked }).catch((error) => labMessage(error.message, true)));
  labEl("lab-expected-visual").addEventListener("change", (event) => annotateCurrent({ expected_visual: event.target.value }).catch((error) => labMessage(error.message, true)));
  labEl("lab-prev").addEventListener("click", async () => {
    lab.index = Math.max(0, lab.index - 1);
    await showCurrentSample();
  });
  labEl("lab-next").addEventListener("click", async () => {
    lab.index = Math.min(lab.samples.length - 1, lab.index + 1);
    await showCurrentSample();
  });
  labEl("lab-grid-toggle").addEventListener("click", async () => {
    lab.grid = !lab.grid;
    labEl("lab-single-annotate").hidden = lab.grid;
    labEl("lab-grid-annotate").hidden = !lab.grid;
    if (lab.grid) await renderGrid();
    else await showCurrentSample();
  });
  labEl("lab-grid-block").addEventListener("click", async () => {
    labAssert(await labInvoke("lab_annotate_selected", Array.from(lab.selected), "block", null));
    await refreshSamples();
  });
  labEl("lab-grid-allow").addEventListener("click", async () => {
    labAssert(await labInvoke("lab_annotate_selected", Array.from(lab.selected), "allow", null));
    await refreshSamples();
  });
  labEl("lab-grid-exclude").addEventListener("click", async () => {
    labAssert(await labInvoke("lab_annotate_selected", Array.from(lab.selected), null, true));
    await refreshSamples();
  });
  document.querySelectorAll("#benchmark-lab input[type=checkbox], #benchmark-lab input[type=radio], #benchmark-lab select").forEach((input) => {
    if ((input.name && input.name.startsWith("lab-")) || (input.id && input.id.startsWith("lab-"))) {
      input.addEventListener("change", () => refreshConfigs().catch(() => {}));
    }
  });
  labEl("lab-apply-config").addEventListener("click", async () => {
    try {
      const config = lab.configs[0];
      const response = labAssert(await labInvoke("lab_apply_config_to_protection", config || null));
      labMessage(response.message);
    } catch (error) {
      labMessage(error.message, true);
    }
  });
  labEl("lab-start-run").addEventListener("click", async () => {
    try {
      await refreshConfigs();
      const response = labAssert(await labInvoke("lab_start_run", configPayload()));
      labMessage(response.message);
    } catch (error) {
      labMessage(error.message, true);
    }
  });
  labEl("lab-cancel-run").addEventListener("click", async () => {
    try {
      const response = labAssert(await labInvoke("lab_cancel_run"));
      labMessage(response.message);
    } catch (error) {
      labMessage(error.message, true);
    }
  });
  labEl("lab-start-diagnostic").addEventListener("click", () => startTool("diagnostic", {
    mode: selectValue("lab-tool-mode", "detector_compare"),
    model: selectValue("lab-tool-model", "viddexa_nano"),
    iterations: Number(selectValue("lab-tool-iterations", "30")),
    width: Number(selectValue("lab-tool-width", "1920")),
    height: Number(selectValue("lab-tool-height", "1080")),
    size: Number(selectValue("lab-tool-size", "640")),
  }).catch((error) => labMessage(error.message, true)));
  labEl("lab-start-capture").addEventListener("click", () => startTool("capture", {
    backend: selectValue("lab-capture-backend", "both"),
    frames: Number(selectValue("lab-capture-frames", "30")),
    warmup: Number(selectValue("lab-capture-warmup", "3")),
  }).catch((error) => labMessage(error.message, true)));
  labEl("lab-start-stability").addEventListener("click", () => startTool("stability", {
    backend: selectValue("lab-stability-backend", "auto"),
    duration_seconds: Number(selectValue("lab-stability-duration", "3600")),
  }).catch((error) => labMessage(error.message, true)));
  labEl("lab-cancel-tool").addEventListener("click", async () => {
    try {
      const response = labAssert(await labInvoke("lab_cancel_tool"));
      labMessage(response.message);
      await pollToolProgress();
    } catch (error) { labMessage(error.message, true); }
  });
  labEl("lab-tool-history-refresh").addEventListener("click", () => refreshToolHistory().catch((error) => labMessage(error.message, true)));
  for (const kind of ["json", "csv"]) {
    labEl(`lab-tool-export-${kind}`).addEventListener("click", async () => {
      try {
        const response = labAssert(await labInvoke("lab_export_tool", lab.toolRunId, kind, null));
        labMessage(`Exported ${response.path}`);
      } catch (error) { labMessage(error.message, true); }
    });
  }
  labEl("lab-score-ranking").addEventListener("click", async () => {
    try {
      const tiles = JSON.parse(labEl("lab-ranking-tiles").value || "[]");
      const response = labAssert(await labInvoke(
        "lab_ranking_fixture", tiles,
        Number(selectValue("lab-ranking-baseline", "0")),
        Number(selectValue("lab-ranking-with-tiles", "0")),
        Number(selectValue("lab-ranking-positives", "0")),
      ));
      labText("lab-ranking-result", JSON.stringify(response, null, 2));
      lab.toolRunId = response.run_id || "";
      await refreshToolHistory();
    } catch (error) { labMessage(error.message, true); }
  });
  labEl("lab-import-high-recall").addEventListener("click", async () => {
    try {
      const response = labAssert(await labInvoke("lab_high_recall_report", null));
      labText("lab-high-recall-result", JSON.stringify(response.report, null, 2));
      lab.toolRunId = response.run_id || "";
      await refreshToolHistory();
    } catch (error) { labMessage(error.message, true); }
  });
  labEl("lab-show-matrix").addEventListener("click", async () => {
    try {
      const response = labAssert(await labInvoke("lab_matrix_preview"));
      labText("lab-high-recall-result", JSON.stringify({ job_count: response.job_count, measurement_targets_only: true, matrix: response.matrix }, null, 2));
    } catch (error) { labMessage(error.message, true); }
  });
  labEl("lab-refresh-failures").addEventListener("click", () => refreshFailures().catch((error) => labMessage(error.message, true)));
  labEl("lab-refresh-compare").addEventListener("click", () => refreshCompare().catch((error) => labMessage(error.message, true)));
  labEl("lab-sort-key").addEventListener("change", () => refreshCompare().catch((error) => labMessage(error.message, true)));
  labEl("lab-run-sweep").addEventListener("click", async () => {
    try {
      const response = labAssert(await labInvoke("lab_sweep", configPayload()));
      const body = (response.rows || []).map((row) => (
        `<tr>
          <td>${row.proposal == null ? "—" : row.proposal}</td>
          <td>${row.strong}</td>
          <td>${percent(row.recall)}</td>
          <td>${percent(row.fnr)}</td>
          <td>${percent(row.fpr)}</td>
          <td>${percent(row.precision)}</td>
          <td>${percent(row.accuracy)}</td>
        </tr>`
      )).join("");
      labEl("lab-sweep").innerHTML = `
        <table>
          <thead>
            <tr><th>Proposal</th><th>Strong</th><th>Recall</th><th>FNR</th><th>FPR</th><th>Precision</th><th>Accuracy</th></tr>
          </thead>
          <tbody>${body || "<tr><td colspan=7>No valid proposal/strong pairs</td></tr>"}</tbody>
        </table>
      `;
    } catch (error) {
      labMessage(error.message, true);
    }
  });
  labEl("lab-export-json").addEventListener("click", async () => {
    try {
      const response = labAssert(await labInvoke("lab_export", "json", null));
      labMessage(`Exported ${response.path}`);
    } catch (error) {
      labMessage(error.message, true);
    }
  });
  labEl("lab-export-csv").addEventListener("click", async () => {
    try {
      const response = labAssert(await labInvoke("lab_export", "csv", null));
      labMessage(`Exported ${response.path}`);
    } catch (error) {
      labMessage(error.message, true);
    }
  });
  labEl("lab-annotated-preview").addEventListener("click", async () => {
    try {
      const sample = currentSample();
      if (!sample) return;
      const response = labAssert(await labInvoke("lab_annotated_preview", sample.id, null));
      const image = labEl("lab-annotated-image");
      image.src = response.preview;
      image.hidden = false;
    } catch (error) {
      labMessage(error.message, true);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (lab.view !== "developer" || lab.tab !== "annotate" || lab.grid) return;
    if (event.target && event.target.matches && event.target.matches("input, textarea, select")) return;
    if (event.key === "b" || event.key === "B") annotateCurrent({ expected: "block" });
    if (event.key === "a" || event.key === "A") annotateCurrent({ expected: "allow" });
    if (event.key === "e" || event.key === "E") {
      const exclude = labEl("lab-exclude");
      annotateCurrent({ excluded: !exclude.checked });
    }
    if (event.key === "ArrowLeft") {
      lab.index = Math.max(0, lab.index - 1);
      showCurrentSample();
    }
    if (event.key === "ArrowRight") {
      lab.index = Math.min(lab.samples.length - 1, lab.index + 1);
      showCurrentSample();
    }
  });
  labInvoke("lab_tag_catalog").then((response) => {
    lab.tags = (response && response.tags) || [];
    renderTagFilters();
  }).catch(() => {});
  refreshDatasets().catch(() => {});
  refreshConfigs().catch(() => {});
  refreshToolHistory().catch(() => {});
  lab.progressTimer = window.setInterval(() => {
    pollProgress().catch(() => {});
    pollToolProgress().catch(() => {});
  }, 1000);
  setView("home");
}

window.addEventListener("pywebviewready", initializeLab, { once: true });
window.addEventListener("beforeunload", () => {
  if (lab.progressTimer) window.clearInterval(lab.progressTimer);
});
