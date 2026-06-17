/**
 * ACCESS-MOPPy Submission Progress Dashboard
 * Reads progress.json compiled by scripts/compile_progress.py
 */

const PROGRESS_URL = "progress.json";
const GITHUB_REPO  = "access-nri/access-moppy-progress";
const QC_REGISTRY_REPO = "https://github.com/access-nri/access-moppy-qc-registry";
const QC_REGISTRY_DASHBOARD = "https://access-nri.github.io/access-moppy-qc-registry/";
const CMOR_REQUEST_TEMPLATE_URL = `https://github.com/${GITHUB_REPO}/issues/new?template=propose_submission.yml`;

// ── Stage metadata ──────────────────────────────────────────────────────────
const STAGES = {
  published:   { label: "Published",   symbol: "★", cls: "published"  },
  ready_for_nci: { label: "Ready for NCI", symbol: "△", cls: "ready_for_nci" },
  qc_checks:   { label: "QC checks",   symbol: "◌", cls: "qc_checks"  },
  cmorised:    { label: "CMORised",    symbol: "✓", cls: "cmorised"   },
  planned:     { label: "Planned",     symbol: "○", cls: "planned"    },
};

const STAGE_PRIORITY = [
  "planned","cmorised","qc_checks","ready_for_nci","published"
];

const REQUEST_STATUS_META = {
  proposed:    { label: "Proposed", cls: "planned" },
  accepted:    { label: "Accepted", cls: "cmorised" },
  in_progress: { label: "In progress", cls: "qc_checks" },
  on_hold:     { label: "On hold", cls: "ready_for_nci" },
  completed:   { label: "Completed", cls: "published" },
  rejected:    { label: "Rejected", cls: "failed" },
};

const REQUEST_STATUS_PRIORITY = ["accepted", "in_progress", "on_hold", "proposed", "completed", "rejected"];

function isDeckExperiment(expInfo) {
  return Boolean(expInfo?.deck);
}

function experimentTheme(expInfo) {
  return expInfo?.theme || (isDeckExperiment(expInfo) ? "deck" : "default");
}

function experimentCardClass(expInfo) {
  const theme = experimentTheme(expInfo);
  return theme === "default" ? "exp-card" : `exp-card exp-card-${theme.replace("_", "-")}`;
}

function renderExperimentTags(expInfo) {
  const tags = expInfo?.tags || [];
  if (!tags.length) return "";
  const tagHtml = tags.map((tag, index) =>
    `<span class="exp-card-label${index > 0 ? " exp-card-label-secondary" : ""}">${escHtml(tag)}</span>`
  ).join("");
  return `<div class="exp-card-labels">${tagHtml}</div>`;
}

function renderExperimentMeta(expInfo) {
  const parts = [];
  if (expInfo?.category) {
    parts.push(`<span class="exp-card-category">${escHtml(expInfo.category)}</span>`);
  }
  const priority = expInfo?.priority || "medium";
  parts.push(`<span class="exp-card-priority">${escHtml(priority)}</span>`);
  return `<div class="exp-card-meta">${parts.join("")}</div>`;
}

function requestIssueUrl(issueNumber) {
  if (!issueNumber) return CMOR_REQUEST_TEMPLATE_URL;
  return `https://github.com/${GITHUB_REPO}/issues/${issueNumber}`;
}

function requestFileUrl(requestFile) {
  if (!requestFile) return `https://github.com/${GITHUB_REPO}`;
  return `https://github.com/${GITHUB_REPO}/blob/main/${requestFile}`;
}

function requestModels() {
  const models = progress.requests?.map(req => req.model).filter(Boolean) || [];
  return [...new Set([...progress.models, ...models])].sort();
}

function requestStatusBadge(status) {
  const meta = REQUEST_STATUS_META[status] || { label: status || "Unknown", cls: "planned" };
  return `<span class="stage stage-${meta.cls}">${escHtml(meta.label)}</span>`;
}

function requestPriorityChip(priority) {
  return `<span class="exp-card-priority">${escHtml(priority || "medium")}</span>`;
}

function requestSearchText(req) {
  return [
    req.model,
    req.experiment,
    req.member,
    req.contact,
    req.requested_by,
    req.gadi?.project,
    req.gadi?.input_folder,
    req.cmip_metadata?.parent_experiment_id,
    req.notes,
  ].filter(Boolean).join(" ").toLowerCase();
}

function requestMatches(req, filterText) {
  if (!filterText) return true;
  return requestSearchText(req).includes(filterText.toLowerCase());
}

function sortRequests(a, b) {
  const aStatus = REQUEST_STATUS_PRIORITY.indexOf(a.status);
  const bStatus = REQUEST_STATUS_PRIORITY.indexOf(b.status);
  if (aStatus !== bStatus) return (aStatus === -1 ? 999 : aStatus) - (bStatus === -1 ? 999 : bStatus);
  return `${a.model}/${a.experiment}/${a.member}`.localeCompare(`${b.model}/${b.experiment}/${b.member}`);
}

function formatRequestVariables(req) {
  if (req.target_variables_mode === "all") return "All planned variables";
  if (req.target_variable_count) return `${req.target_variable_count} requested variable${req.target_variable_count === 1 ? "" : "s"}`;
  return "Subset requested";
}

function formatRequestProgress(req) {
  const summary = req.progress_summary;
  if (!summary) return `<span class="request-progress-empty">No CMORisation report yet</span>`;
  const total = summary.total_planned || 0;
  return `${progressBar(summary, total)}<div class="request-progress-copy">${countChips(summary)}</div>`;
}

function buildGapIssueUrl(gap) {
  const title = `[cmorisation] ${gap.model} ${gap.experiment} ${gap.member}`;
  return `${CMOR_REQUEST_TEMPLATE_URL}&title=${encodeURIComponent(title)}`;
}

function experimentsForModel(model) {
  return Object.keys(progress.index[model]?.experiments || {}).sort();
}

function membersFor(model, experiment) {
  return progress.index[model]?.experiments?.[experiment]?.members || [];
}

function buildOptions(items, selected) {
  return items.map(item => `<option${item===selected ? " selected" : ""}>${item}</option>`).join("");
}

function categoriesForModel(model) {
  const experiments = Object.values(progress.index[model]?.experiments || {});
  return [...new Set(experiments.map(exp => exp.category).filter(Boolean))].sort();
}

function isDummyExperiment(expInfo) {
  return (expInfo?.tags || []).includes("DUMMY");
}

function overviewGroupKey(expInfo) {
  if (isDummyExperiment(expInfo)) return "dummy";
  return experimentTheme(expInfo);
}

function variableSearchText(unit) {
  return [
    unit.variable,
    unit.variable_short,
    unit.variable_cmip7,
  ].filter(Boolean).join(" ").toLowerCase();
}

function variableMatches(unit, filterText) {
  if (!filterText) return true;
  return variableSearchText(unit).includes(filterText.toLowerCase());
}

function variableLabelHtml(unit) {
  const primary = escHtml(unit.variable);
  const extras = [unit.variable_short, unit.variable_cmip7]
    .filter(value => value && value !== unit.variable)
    .map(value => escHtml(value));
  const hoverParts = [unit.variable_description, unit.variable_notes].filter(Boolean);
  const titleAttr = hoverParts.length
    ? ` title="${escHtml(hoverParts.join(" — "))}"`
    : "";
  if (!extras.length) {
    return `<code${titleAttr}>${primary}</code>`;
  }
  return `<div class="variable-label"${titleAttr}><code>${primary}</code><span>${extras.join(" · ")}</span></div>`;
}

function variableLookupUnit(variable) {
  return progress.units.find(unit => unit.variable === variable) || null;
}

function variableContextLabel(context) {
  if (!context?.experiment) return "Variable-wide QC context";
  const parts = [context.model, context.experiment, context.member].filter(Boolean);
  return `Experiment-specific QC context: ${parts.join(" / ")}`;
}

function variableScopeOptions(context, selected) {
  const options = [];
  if (context?.experiment) {
    options.push(["context", "Selected experiment only"]);
  }
  options.push(["all", "All experiments"]);
  return options.map(([value, label]) =>
    `<option value="${value}"${value === selected ? " selected" : ""}>${label}</option>`
  ).join("");
}

function matchesVariableContext(unit, context) {
  if (!context?.experiment) return true;
  if (context.model && unit.model !== context.model) return false;
  return unit.experiment === context.experiment;
}

function buildQcRegistrySearchUrl(unit, context) {
  const params = new URLSearchParams();
  if (unit?.variable) params.set("variable", unit.variable);
  if (unit?.variable_short) params.set("short_name", unit.variable_short);
  if (unit?.variable_cmip7) params.set("cmip7_name", unit.variable_cmip7);
  if (context?.model) params.set("model", context.model);
  if (context?.experiment) params.set("experiment", context.experiment);
  if (context?.member) params.set("member", context.member);
  const query = params.toString();
  return query ? `${QC_REGISTRY_DASHBOARD}?${query}` : QC_REGISTRY_DASHBOARD;
}

function buildQcSuggestionUrl(unit, context) {
  const title = context?.experiment
    ? `QC check suggestion for ${unit.variable} in ${context.experiment}`
    : `QC check suggestion for ${unit.variable}`;
  const body = [
    `Variable: ${unit.variable}`,
    unit.variable_short ? `Short name: ${unit.variable_short}` : null,
    unit.variable_cmip7 ? `CMIP7 name: ${unit.variable_cmip7}` : null,
    context?.model ? `Model: ${context.model}` : null,
    context?.experiment ? `Experiment: ${context.experiment}` : null,
    context?.member ? `Member: ${context.member}` : null,
    "",
    "Suggested additional QC checks:",
    "- ",
    "",
    "Why this would be useful:",
    "- ",
  ].filter(Boolean).join("\n");
  return `${QC_REGISTRY_REPO}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
}

function renderVariableActions(unit, context) {
  const registryUrl = buildQcRegistrySearchUrl(unit, context);
  const variableWideRegistryUrl = buildQcRegistrySearchUrl(unit, null);
  const suggestionUrl = buildQcSuggestionUrl(unit, context);
  return `
    <div class="variable-resource-card">
      <div>
        <div class="variable-resource-title">QC registry companion</div>
        <div class="variable-resource-copy">
          Use the companion QC registry to inspect checks for this variable or suggest new ones.
        </div>
        <div class="variable-resource-context">${escHtml(variableContextLabel(context))}</div>
      </div>
      <div class="variable-resource-actions">
        <a class="resource-btn" href="${registryUrl}" target="_blank" rel="noopener">${context?.experiment ? "View checks for this experiment" : "View QC checks"}</a>
        ${context?.experiment ? `<a class="resource-btn resource-btn-secondary" href="${variableWideRegistryUrl}" target="_blank" rel="noopener">View variable-wide checks</a>` : ""}
        <a class="resource-btn resource-btn-secondary" href="${suggestionUrl}" target="_blank" rel="noopener">Suggest checks</a>
      </div>
    </div>
  `;
}

function themeLabel(theme) {
  if (theme === "dummy") return "TESTING / DUMMY";
  if (theme === "deck") return "DECK";
  if (theme === "fast_track") return "FAST TRACK";
  return "Other Experiments";
}

function worstStage(stages) {
  return stages.reduce((a, b) => {
    const ai = STAGE_PRIORITY.indexOf(a); const bi = STAGE_PRIORITY.indexOf(b);
    return (ai === -1 || bi < ai) ? b : a;
  }, "published");
}

function displayStage(stage) {
  if (stage === "published") return "published";
  if (stage === "qc_pass" || stage === "qc_warn") return "ready_for_nci";
  if (stage === "cmorised") return "cmorised";
  if (["qc_fail", "qc_pending", "failed"].includes(stage)) return "qc_checks";
  return "planned";
}

// ── App state ───────────────────────────────────────────────────────────────
let progress = null;
let currentView = "overview";
let currentVariableContext = null;

// ── Bootstrap ───────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  document.querySelectorAll(".nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentView = btn.dataset.view;
      renderView();
    });
  });

  try {
    const resp = await fetch(PROGRESS_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    progress = await resp.json();
  } catch (err) {
    document.getElementById("app").innerHTML =
      `<p style="color:var(--c-failed)">Failed to load progress.json: ${err.message}</p>`;
    return;
  }

  const totalUnits = progress.units.length;
  const done = progress.units.filter(u => u.cmorisation_status === "completed").length;
  const requestCount = progress.requests?.length || 0;
  document.getElementById("meta").textContent =
    `Generated ${new Date(progress.generated_at).toLocaleString()} · ` +
    `${totalUnits} units · ${done} cmorised or beyond · ${requestCount} CMOR requests`;

  renderView();
});

function renderView() {
  const app = document.getElementById("app");
  app.innerHTML = "";
  if (currentView === "overview")    renderOverview(app);
  if (currentView === "experiment")  renderExperimentDetail(app);
  if (currentView === "member")      renderMemberTimeline(app);
  if (currentView === "variable")    renderVariablePipeline(app, currentVariableContext);
  if (currentView === "requests")    renderRequestsView(app);
}

function openVariableView(variable, context = {}) {
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.querySelector('[data-view="variable"]').classList.add("active");
  currentView = "variable";
  currentVariableContext = {
    variable,
    model: context.model || null,
    experiment: context.experiment || null,
    member: context.member || null,
  };
  renderVariablePipeline(document.getElementById("app"), currentVariableContext);
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function unitsFor(model, experiment, member) {
  return progress.units.filter(u =>
    (!model      || u.model      === model) &&
    (!experiment || u.experiment === experiment) &&
    (!member     || u.member     === member)
  );
}

function stageCell(stage) {
  const s = STAGES[displayStage(stage)] || STAGES.planned;
  return `<td class="cell-${s.cls}" title="${s.label}">${s.symbol}</td>`;
}

function stageBadge(stage) {
  const s = STAGES[displayStage(stage)] || STAGES.planned;
  return `<span class="stage stage-${s.cls}">${s.label}</span>`;
}

function normalizeStatusForDisplay(status) {
  if (status === "completed") return "cmorised";
  if (status === "running" || status === "pending" || status === "retrying") return "planned";
  if (status === "not_published" || status === "retracted") return "not_started";
  return status;
}

function qcStatusForDisplay(unit) {
  const stage = unit.pipeline_stage;
  if (stage === "published") return "qc_pass";
  if (stage === "qc_pass" || stage === "qc_warn" || stage === "qc_fail" || stage === "qc_pending") {
    return stage;
  }
  if (stage === "failed") return "failed";
  if (stage === "cmorised") return "planned";
  return "not_started";
}

function simpleStatusBadge(kind) {
  if (kind === "passed") return `<span class="stage stage-qc_pass">✓</span>`;
  if (kind === "failed") return `<span class="stage stage-failed">✗</span>`;
  return `<span class="stage stage-not_started">Not started</span>`;
}

function cmorSimpleStatus(unit) {
  if (unit.cmorisation_status === "completed") return "passed";
  if (unit.cmorisation_status === "failed") return "failed";
  return "not_started";
}

function qcSimpleStatus(unit) {
  const stage = unit.pipeline_stage;
  if (stage === "published" || stage === "qc_pass" || stage === "qc_warn") return "passed";
  if (stage === "qc_fail" || stage === "failed") return "failed";
  return "not_started";
}

function publicationSimpleStatus(unit) {
  if (unit.publication_status === "published") return "passed";
  if (unit.publication_status === "retracted") return "failed";
  return "not_started";
}

function progressBar(summary, total) {
  if (!total) return "";
  const segments = [
    ["published",  summary.published  || 0, "seg-published"],
    ["ready_for_nci", (summary.qc_pass || 0) + (summary.qc_warn || 0), "seg-ready-for-nci"],
    ["qc_checks",  (summary.qc_fail || 0) + (summary.qc_pending || 0) + (summary.failed || 0), "seg-qc-checks"],
    ["cmorised",   summary.cmorised   || 0, "seg-cmorised"],
    ["planned",    (summary.not_started || 0) + (summary.planned || 0), "seg-planned"],
  ];
  const bars = segments
    .filter(([,n]) => n > 0)
    .map(([,n,cls]) => `<div class="progress-segment ${cls}" style="width:${(n/total*100).toFixed(1)}%" title="${n}"></div>`)
    .join("");
  return `<div class="progress-wrap">${bars}</div>`;
}

function countChips(summary) {
  const parts = [];
  const checks = [
    ["Published", "chip-published", summary.published || 0],
    ["Ready for NCI", "chip-ready-for-nci", (summary.qc_pass || 0) + (summary.qc_warn || 0)],
    ["QC checks", "chip-qc-checks", (summary.qc_fail || 0) + (summary.qc_pending || 0) + (summary.failed || 0)],
    ["CMORised", "chip-cmorised", summary.cmorised || 0],
    ["Planned", "chip-planned", (summary.planned || 0) + (summary.not_started || 0)],
  ];
  for (const [label, cls, n] of checks) {
    if (n) parts.push(`<span class="chip ${cls}">${n} ${label}</span>`);
  }
  return `<div class="count-chips">${parts.join("")}</div>`;
}

function makeLegend(stages) {
  return `<div class="legend">${stages.map(s => {
    const st = STAGES[s] || {};
    return `<span class="legend-item"><span class="legend-swatch cell-${st.cls}"></span>${st.label}</span>`;
  }).join("")}</div>`;
}

// ── View: Overview ───────────────────────────────────────────────────────────
function renderOverview(container) {
  const title = h("div", "view-title", "Submission Overview");
  const sub   = h("div", "view-sub",
    "Each card = one experiment. Rows = ensemble members. Bars show pipeline stage breakdown.");
  container.appendChild(title);
  container.appendChild(sub);

  const models = progress.models;
  let selModel = models[0];
  let selCategory = "All categories";

  const controls = document.createElement("div");
  controls.className = "controls";
  controls.innerHTML = `
    <label>Model</label>
    <select id="overview-model">${buildOptions(models, selModel)}</select>
    <label>Category</label>
    <select id="overview-category">${buildOptions(["All categories", ...categoriesForModel(selModel)], selCategory)}</select>
  `;
  container.appendChild(controls);
  container.appendChild(el(makeLegend(["planned","cmorised","qc_checks","ready_for_nci","published"])));

  const content = document.createElement("div");
  container.appendChild(content);

  function redraw() {
    content.innerHTML = "";
    const modelHead = h("div", "view-title", selModel);
    modelHead.style.cssText = "font-size:0.9rem;margin-top:1.5rem;margin-bottom:0.75rem;";
    content.appendChild(modelHead);

    const expIndex = progress.index[selModel]?.experiments || {};
    const grouped = { dummy: [], deck: [], fast_track: [], default: [] };

    for (const [expId, expInfo] of Object.entries(expIndex)) {
      if (selCategory !== "All categories" && expInfo.category !== selCategory) {
        continue;
      }
      const group = overviewGroupKey(expInfo);
      if (!grouped[group]) grouped[group] = [];
      grouped[group].push([expId, expInfo]);
    }

    const themeOrder = ["dummy", "deck", "fast_track", "default"];
    let renderedCount = 0;

    for (const theme of themeOrder) {
      const experiments = grouped[theme] || [];
      if (!experiments.length) continue;

      const section = document.createElement("section");
      section.className = `overview-section overview-section-${theme.replace("_", "-")}`;

      const sectionHead = document.createElement("div");
      sectionHead.className = "overview-section-head";
      sectionHead.innerHTML = `
        <h3>${themeLabel(theme)}</h3>
        <p>${theme === "dummy" ? "Synthetic experiments for dashboard testing and visual QA." : theme === "deck" ? "Core DECK experiments and related baseline runs." : theme === "fast_track" ? "FAST TRACK experiments coordinated through CSIRO." : "Additional experiments."}</p>
      `;
      section.appendChild(sectionHead);

      const grid = document.createElement("div");
      grid.className = "overview-grid";

      for (const [expId, expInfo] of experiments) {
        const members = expInfo.members || [];
        const card = document.createElement("div");
        card.className = experimentCardClass(expInfo);
        const title = expInfo.label || expId;
        card.innerHTML = `
          ${renderExperimentTags(expInfo)}
          <h3>${escHtml(title)}</h3>
          ${renderExperimentMeta(expInfo)}
          <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.5rem">${members.length} member${members.length!==1?"s":""}</div>
        `;

        const table = document.createElement("table");
        table.className = "members-table";
        table.innerHTML = `<thead><tr><th>Member</th><th>Progress</th><th>Breakdown</th></tr></thead>`;
        const tbody = document.createElement("tbody");

        for (const member of members) {
          const key = `${selModel}/${expId}/${member}`;
          const summary = progress.summaries[key] || {};
          const total = summary.total_planned || 1;
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td><span class="member-label" data-model="${selModel}" data-exp="${expId}" data-member="${member}">${member}</span></td>
            <td>${progressBar(summary, total)}<span style="font-size:0.7rem;color:var(--text-muted)">${total}</span></td>
            <td>${countChips(summary)}</td>
          `;
          tbody.appendChild(tr);
        }

        table.appendChild(tbody);
        card.appendChild(table);
        grid.appendChild(card);
        renderedCount += 1;
      }

      section.appendChild(grid);
      content.appendChild(section);
    }

    if (!renderedCount) {
      content.innerHTML += "<p style='color:var(--text-muted)'>No experiments match this category.</p>";
    }
  }

  controls.querySelector("#overview-model").addEventListener("change", e => {
    selModel = e.target.value;
    selCategory = "All categories";
    controls.querySelector("#overview-category").innerHTML =
      buildOptions(["All categories", ...categoriesForModel(selModel)], selCategory);
    redraw();
  });
  controls.querySelector("#overview-category").addEventListener("change", e => {
    selCategory = e.target.value;
    redraw();
  });

  redraw();

  container.addEventListener("click", event => {
    const lnk = event.target.closest("[data-member]");
    if (!lnk) return;
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
    document.querySelector('[data-view="member"]').classList.add("active");
    currentView = "member";
    renderMemberTimeline(document.getElementById("app"), lnk.dataset.model, lnk.dataset.exp, lnk.dataset.member);
  });
}

// ── View: Experiment Detail ──────────────────────────────────────────────────
function renderExperimentDetail(container, preModel, preExp) {
  container.innerHTML = "";
  const models = progress.models;

  let selModel = preModel || models[0];
  let selExp   = preExp   || experimentsForModel(selModel)[0];

  const controls = document.createElement("div");
  controls.className = "controls";
  controls.innerHTML = `
    <label>Model</label>
    <select id="sel-model">${buildOptions(models, selModel)}</select>
    <label>Experiment</label>
    <select id="sel-exp">${buildOptions(experimentsForModel(selModel), selExp)}</select>
    <label>Filter variable</label>
    <input id="var-filter" type="text" placeholder="e.g. Amon.tos or ocean.tos..." style="width:240px"/>
  `;

  const title = h("div", "view-title", "Experiment Detail");
  const sub   = h("div", "view-sub", "Rows = variables · Columns = ensemble members · Click a cell for details.");
  container.appendChild(title);
  container.appendChild(sub);
  container.appendChild(controls);
  container.appendChild(el(makeLegend(["planned","cmorised","qc_checks","ready_for_nci","published"])));

  const wrap = document.createElement("div");
  container.appendChild(wrap);

  let varFilter = "";

  function redraw() {
    wrap.innerHTML = "";
    const units = unitsFor(selModel, selExp, null);
    const members = [...new Set(units.map(u => u.member))].sort();
    const variableUnits = [];
    const seen = new Set();
    for (const unit of units) {
      if (seen.has(unit.variable)) continue;
      seen.add(unit.variable);
      variableUnits.push(unit);
    }
    let variables = variableUnits.filter(unit => variableMatches(unit, varFilter));
    variables.sort((a, b) => a.variable.localeCompare(b.variable));
    if (!variables.length) {
      wrap.innerHTML = "<p style='color:var(--text-muted)'>No data for this selection.</p>";
      return;
    }

    const byKey = {};
    for (const u of units) byKey[`${u.variable}__${u.member}`] = u;

    const scrollDiv = document.createElement("div");
    scrollDiv.className = "scroll";
    const table = document.createElement("table");
    table.className = "matrix";

    const thead = table.createTHead();
    const hr = thead.insertRow();
    hr.insertCell().outerHTML = "<th>Variable</th>";
    for (const m of members) hr.insertCell().outerHTML = `<th style="font-family:var(--mono);font-size:0.75rem">${m}</th>`;

    const tbody = table.createTBody();
    for (const variableUnit of variables) {
      const v = variableUnit.variable;
      const row = tbody.insertRow();
      const th = document.createElement("th");
      th.innerHTML = `<span class="variable-link" data-var="${escHtml(v)}">${variableLabelHtml(variableUnit)}</span>`;
      row.appendChild(th);
      for (const m of members) {
        const u = byKey[`${v}__${m}`];
        const stage = displayStage(u ? u.pipeline_stage : "planned");
        const s = STAGES[stage] || STAGES.planned;
        row.insertCell().outerHTML = `<td class="cell-${s.cls}" title="${s.label} — ${v} / ${m}">${s.symbol}</td>`;
      }
    }
    scrollDiv.appendChild(table);
    wrap.appendChild(scrollDiv);
  }

  controls.querySelector("#sel-model").addEventListener("change", e => {
    selModel = e.target.value;
    selExp = experimentsForModel(selModel)[0];
    controls.querySelector("#sel-exp").innerHTML = buildOptions(experimentsForModel(selModel), selExp);
    redraw();
  });
  controls.querySelector("#sel-exp").addEventListener("change",   e => { selExp   = e.target.value; redraw(); });
  controls.querySelector("#var-filter").addEventListener("input",  e => { varFilter = e.target.value.trim(); redraw(); });
  wrap.addEventListener("click", event => {
    const lnk = event.target.closest("[data-var]");
    if (!lnk) return;
    openVariableView(lnk.dataset.var, { model: selModel, experiment: selExp });
  });

  redraw();
}

// ── View: Member Timeline ────────────────────────────────────────────────────
function renderMemberTimeline(container, preModel, preExp, preMember) {
  container.innerHTML = "";

  const models   = progress.models;

  let selModel  = preModel  || models[0];
  let selExp    = preExp    || experimentsForModel(selModel)[0];
  let selMember = preMember || membersFor(selModel, selExp)[0];

  const controls = document.createElement("div");
  controls.className = "controls";
  controls.innerHTML = `
    <label>Model</label>
    <select id="sel-model">${buildOptions(models, selModel)}</select>
    <label>Experiment</label>
    <select id="sel-exp">${buildOptions(experimentsForModel(selModel), selExp)}</select>
    <label>Member</label>
    <select id="sel-member">${buildOptions(membersFor(selModel, selExp), selMember)}</select>
  `;

  const title = h("div", "view-title", "Member Timeline");
  const sub   = h("div", "view-sub", "All variables for a single (model, experiment, member) — ordered by overall progress.");
  container.appendChild(title);
  container.appendChild(sub);
  container.appendChild(controls);

  const wrap = document.createElement("div");
  container.appendChild(wrap);

  function redraw() {
    wrap.innerHTML = "";
    const units = unitsFor(selModel, selExp, selMember);
    if (!units.length) {
      wrap.innerHTML = "<p style='color:var(--text-muted)'>No data for this combination. Has a batch report been ingested yet?</p>";
      return;
    }

    // Summary bar
    const key = `${selModel}/${selExp}/${selMember}`;
    const summary = progress.summaries[key] || {};
    const total   = summary.total_planned || units.length;

    const summaryDiv = document.createElement("div");
    summaryDiv.style.cssText = "margin-bottom:1rem;";
    summaryDiv.innerHTML = `
      ${progressBar(summary, total)}
      <div style="margin-top:0.5rem">${countChips(summary)}</div>
    `;
    wrap.appendChild(summaryDiv);

    // Sort by pipeline stage priority (worst first so failures are visible)
    const sorted = [...units].sort((a, b) =>
      STAGE_PRIORITY.indexOf(displayStage(a.pipeline_stage)) - STAGE_PRIORITY.indexOf(displayStage(b.pipeline_stage))
    );

    const scrollDiv = document.createElement("div");
    scrollDiv.className = "scroll";
    const table = document.createElement("table");
    table.className = "detail";
    table.innerHTML = `<thead><tr><th>Variable</th><th>CMORisation</th><th>QC Checks</th><th>Publication</th></tr></thead>`;
    const tbody = document.createElement("tbody");
    for (const u of sorted) {
      const qcStatus = qcSimpleStatus(u);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${variableLabelHtml(u)}</td>
        <td>${simpleStatusBadge(cmorSimpleStatus(u))}</td>
        <td><span class="timeline-qc-cell" data-var="${escHtml(u.variable)}" title="Open variable pipeline for ${escHtml(u.variable)}">${simpleStatusBadge(qcStatus)}</span></td>
        <td>${simpleStatusBadge(publicationSimpleStatus(u))}</td>
      `;
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    scrollDiv.appendChild(table);
    wrap.appendChild(scrollDiv);
  }

  controls.querySelector("#sel-model").addEventListener("change",  e => {
    selModel = e.target.value;
    selExp = experimentsForModel(selModel)[0];
    controls.querySelector("#sel-exp").innerHTML = buildOptions(experimentsForModel(selModel), selExp);
    selMember = membersFor(selModel, selExp)[0];
    controls.querySelector("#sel-member").innerHTML = buildOptions(membersFor(selModel, selExp), selMember);
    redraw();
  });
  controls.querySelector("#sel-exp").addEventListener("change",    e => {
    selExp = e.target.value;
    selMember = membersFor(selModel, selExp)[0];
    controls.querySelector("#sel-member").innerHTML = buildOptions(membersFor(selModel, selExp), selMember);
    redraw();
  });
  controls.querySelector("#sel-member").addEventListener("change", e => { selMember = e.target.value; redraw(); });
  wrap.addEventListener("click", event => {
    const lnk = event.target.closest("[data-var]");
    if (!lnk) return;
    openVariableView(lnk.dataset.var, { model: selModel, experiment: selExp, member: selMember });
  });

  redraw();
}

// ── View: Variable Pipeline ──────────────────────────────────────────────────
function renderVariablePipeline(container, selection) {
  container.innerHTML = "";

  const allVarUnits = [];
  const seen = new Set();
  for (const unit of progress.units) {
    if (seen.has(unit.variable)) continue;
    seen.add(unit.variable);
    allVarUnits.push(unit);
  }
  allVarUnits.sort((a, b) => a.variable.localeCompare(b.variable));
  let varFilter = "";
  const initialVariable = typeof selection === "string"
    ? selection
    : selection?.variable || "";
  const initialContext = typeof selection === "string" ? null : selection || null;
  let scopeMode = initialContext?.experiment ? "context" : "all";

  const controls = document.createElement("div");
  controls.className = "controls";
  controls.innerHTML = `
    <label>Search</label>
    <input id="var-search" type="text" placeholder="e.g. Amon.tos or ocean.tos..." style="width:240px"/>
    <label>Variable</label>
    <select id="sel-var" style="max-width:200px">
      <option value="">— select —</option>
    </select>
    <label>Scope</label>
    <select id="scope-mode">${variableScopeOptions(initialContext, scopeMode)}</select>
  `;

  const title = h("div", "view-title", "Variable Pipeline");
  const sub   = h("div", "view-sub",
    "For one variable: pipeline stage across all (model, experiment, member) combinations.");
  container.appendChild(title);
  container.appendChild(sub);
  container.appendChild(controls);

  const wrap = document.createElement("div");
  container.appendChild(wrap);

  function refreshVariableOptions(selectedValue = "") {
    const sel = controls.querySelector("#sel-var");
    const filtered = allVarUnits.filter(unit => variableMatches(unit, varFilter));
    sel.innerHTML = `
      <option value="">— select —</option>
      ${filtered.map(unit => `<option value="${unit.variable}"${unit.variable===selectedValue ? " selected" : ""}>${escHtml(unit.variable)}</option>`).join("")}
    `;
  }

  function redraw(variable, context = null) {
    wrap.innerHTML = "";
    if (!variable) return;
    const units = progress.units.filter(u => u.variable === variable);
    if (!units.length) {
      wrap.innerHTML = "<p style='color:var(--text-muted)'>No data for this variable.</p>";
      return;
    }

    const variableUnit = variableLookupUnit(variable) || units[0];
    wrap.appendChild(el(renderVariableActions(variableUnit, context)));

    const scopedUnits = scopeMode === "context" && context?.experiment
      ? units.filter(unit => matchesVariableContext(unit, context))
      : units;
    const displayUnits = scopedUnits.length ? scopedUnits : units;

    const models     = [...new Set(displayUnits.map(u => u.model))].sort();
    const experiments= [...new Set(displayUnits.map(u => u.experiment))].sort();
    const members    = [...new Set(displayUnits.map(u => u.member))].sort();

    const byKey = {};
    for (const u of displayUnits) byKey[`${u.model}__${u.experiment}__${u.member}`] = u;

    const scrollDiv = document.createElement("div");
    scrollDiv.className = "scroll";
    const table = document.createElement("table");
    table.className = "matrix";

    const thead = table.createTHead();
    const hr = thead.insertRow();
    hr.insertCell().outerHTML = "<th>Model</th>";
    hr.insertCell().outerHTML = "<th>Experiment</th>";
    for (const m of members) {
      hr.insertCell().outerHTML = `<th style="font-family:var(--mono);font-size:0.75rem">${m}</th>`;
    }

    const tbody = table.createTBody();
    for (const model of models) {
      for (const exp of experiments) {
        const hasAny = members.some(m => byKey[`${model}__${exp}__${m}`]);
        if (!hasAny) continue;
        const row = tbody.insertRow();
        const th1 = document.createElement("th");
        th1.textContent = model;
        row.appendChild(th1);
        const th2 = document.createElement("th");
        th2.style.cssText = "font-family:var(--mono);font-size:0.78rem";
        th2.textContent = exp;
        row.appendChild(th2);
        for (const m of members) {
          const u = byKey[`${model}__${exp}__${m}`];
          const stage = displayStage(u ? u.pipeline_stage : "planned");
          const s = STAGES[stage] || STAGES.planned;
          row.insertCell().outerHTML = `<td class="cell-${s.cls}" title="${s.label} — ${exp}/${m}">${s.symbol}</td>`;
        }
      }
    }

    scrollDiv.appendChild(table);
    wrap.appendChild(el(makeLegend(["planned","cmorised","qc_checks","ready_for_nci","published"])));
    wrap.appendChild(scrollDiv);
  }

  const sel = controls.querySelector("#sel-var");
  refreshVariableOptions(initialVariable);
  if (initialVariable) redraw(initialVariable, initialContext);
  controls.querySelector("#var-search").addEventListener("input", e => {
    varFilter = e.target.value.trim();
    const selected = sel.value;
    refreshVariableOptions(selected);
    if (sel.value !== selected) {
      wrap.innerHTML = "";
    }
  });
  sel.addEventListener("change", e => {
    currentVariableContext = { variable: e.target.value };
    scopeMode = "all";
    controls.querySelector("#scope-mode").innerHTML = variableScopeOptions(currentVariableContext, scopeMode);
    redraw(e.target.value, currentVariableContext);
  });
  controls.querySelector("#scope-mode").addEventListener("change", e => {
    scopeMode = e.target.value;
    redraw(sel.value, currentVariableContext);
  });
}

// ── View: CMOR Requests ─────────────────────────────────────────────────────
function renderRequestsView(container) {
  container.innerHTML = "";

  const requests = [...(progress.requests || [])].sort(sortRequests);
  const gaps = progress.request_gaps || [];
  const models = ["All models", ...requestModels()];
  const statuses = ["All statuses", ...REQUEST_STATUS_PRIORITY.filter(status =>
    requests.some(req => req.status === status)
  )];

  let selModel = models[0];
  let selStatus = statuses[0];
  let searchText = "";

  const title = h("div", "view-title", "CMORisation Work Requests");
  const sub = h(
    "div",
    "view-sub",
    "Requests opened through GitHub issues, plus any planned experiment/member combinations that still need retrospective request metadata."
  );
  container.appendChild(title);
  container.appendChild(sub);

  const controls = document.createElement("div");
  controls.className = "controls";
  controls.innerHTML = `
    <label>Model</label>
    <select id="req-model">${buildOptions(models, selModel)}</select>
    <label>Status</label>
    <select id="req-status">${buildOptions(statuses, selStatus)}</select>
    <label>Search</label>
    <input id="req-search" type="text" placeholder="experiment, member, contact, Gadi path..." style="width:280px"/>
    <a class="resource-btn" href="${CMOR_REQUEST_TEMPLATE_URL}" target="_blank" rel="noopener">Request CMORisation work</a>
    <a class="resource-btn resource-btn-secondary" href="https://github.com/${GITHUB_REPO}/issues?q=is%3Aissue+label%3Atype%2Fsubmission-request" target="_blank" rel="noopener">View GitHub issues</a>
  `;
  container.appendChild(controls);

  const gapWrap = document.createElement("div");
  const listWrap = document.createElement("div");
  listWrap.className = "request-grid";
  container.appendChild(gapWrap);
  container.appendChild(listWrap);

  function redrawGaps() {
    if (!gaps.length) {
      gapWrap.innerHTML = "";
      return;
    }
    const filteredGaps = gaps.filter(gap => selModel === "All models" || gap.model === selModel);
    if (!filteredGaps.length) {
      gapWrap.innerHTML = "";
      return;
    }
    gapWrap.innerHTML = `
      <div class="request-gap-panel">
        <h3>Planned combinations missing a request issue</h3>
        <p>These experiment/member combinations exist in the dashboard plan but do not yet have a request record in <code>requests/</code>. This is the retrospective backfill list.</p>
        <div class="request-gap-list">
          ${filteredGaps.map(gap => `
            <div class="request-gap-item">
              <div>
                <strong>${escHtml(gap.model)}</strong>
                <span>${escHtml(gap.experiment)} / ${escHtml(gap.member)}</span>
              </div>
              <a class="resource-btn resource-btn-secondary" href="${buildGapIssueUrl(gap)}" target="_blank" rel="noopener">Open request issue</a>
            </div>
          `).join("")}
        </div>
      </div>
    `;
  }

  function redrawRequests() {
    const filtered = requests.filter(req =>
      (selModel === "All models" || req.model === selModel) &&
      (selStatus === "All statuses" || req.status === selStatus) &&
      requestMatches(req, searchText)
    );

    if (!filtered.length) {
      listWrap.innerHTML = "<p style='color:var(--text-muted)'>No request matches this filter.</p>";
      return;
    }

    listWrap.innerHTML = filtered.map(req => `
      <article class="request-card${req.in_plan ? "" : " request-card-warning"}">
        <div class="request-card-head">
          <div>
            <div class="request-card-kicker">${escHtml(req.model)}</div>
            <h3>${escHtml(req.experiment)} <span>/ ${escHtml(req.member)}</span></h3>
          </div>
          <div class="request-card-statuses">
            ${requestStatusBadge(req.status)}
            ${requestPriorityChip(req.priority)}
          </div>
        </div>
        <div class="request-meta">
          <span><strong>Parent:</strong> ${escHtml(req.cmip_metadata?.parent_experiment_id || "Standalone / not set")}</span>
          <span><strong>Variables:</strong> ${escHtml(formatRequestVariables(req))}</span>
          <span><strong>Contact:</strong> ${escHtml(req.contact || "Not set")}</span>
          <span><strong>Requested by:</strong> ${escHtml(req.requested_by || "Not set")}</span>
          <span><strong>Requested:</strong> ${escHtml(req.requested_at || "Not set")}</span>
          <span><strong>Accepted:</strong> ${escHtml(req.accepted_at || "Not set")}</span>
          <span><strong>In plan:</strong> ${req.in_plan ? "Yes" : "No"}</span>
        </div>
        <div class="request-paths">
          <div><strong>Gadi input:</strong> <code>${escHtml(req.gadi?.input_folder || "Not set")}</code></div>
          ${req.gadi?.output_folder ? `<div><strong>Output:</strong> <code>${escHtml(req.gadi.output_folder)}</code></div>` : ""}
        </div>
        ${req.notes ? `<p class="request-notes">${escHtml(req.notes)}</p>` : ""}
        <div class="request-progress">
          <div class="request-progress-title">Progress</div>
          ${formatRequestProgress(req)}
        </div>
        <div class="request-actions">
          <a class="resource-btn" href="${requestIssueUrl(req.issue)}" target="_blank" rel="noopener">${req.issue ? `Issue #${req.issue}` : "Open issue template"}</a>
          <a class="resource-btn resource-btn-secondary" href="${requestFileUrl(req.request_file)}" target="_blank" rel="noopener">View request YAML</a>
        </div>
      </article>
    `).join("");
  }

  controls.querySelector("#req-model").addEventListener("change", e => {
    selModel = e.target.value;
    redrawGaps();
    redrawRequests();
  });
  controls.querySelector("#req-status").addEventListener("change", e => {
    selStatus = e.target.value;
    redrawRequests();
  });
  controls.querySelector("#req-search").addEventListener("input", e => {
    searchText = e.target.value.trim();
    redrawRequests();
  });

  redrawGaps();
  redrawRequests();
}

// ── DOM utilities ────────────────────────────────────────────────────────────
function h(tag, cls, text) {
  const el = document.createElement(tag);
  el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
}
function el(html) {
  const div = document.createElement("div");
  div.innerHTML = html;
  return div.firstElementChild || div;
}
function escHtml(s) {
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
