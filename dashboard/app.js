/**
 * ACCESS-MOPPy Submission Progress Dashboard
 * Reads progress.json compiled by scripts/compile_progress.py
 */

const PROGRESS_URL = "progress.json";
const GITHUB_REPO  = "rbeucher/access-moppy-progress";

// ── Stage metadata ──────────────────────────────────────────────────────────
const STAGES = {
  published:   { label: "Published",   symbol: "★", cls: "published"  },
  qc_pass:     { label: "QC Pass",     symbol: "✓", cls: "qc_pass"    },
  qc_warn:     { label: "QC Warn",     symbol: "!", cls: "qc_warn"    },
  qc_fail:     { label: "QC Fail",     symbol: "✗", cls: "qc_fail"    },
  qc_pending:  { label: "QC Pending",  symbol: "?", cls: "qc_pending" },
  cmorised:    { label: "CMORised",    symbol: "✓", cls: "cmorised"   },
  failed:      { label: "Failed",      symbol: "✗", cls: "failed"     },
  not_started: { label: "Not started", symbol: "·", cls: "not_started"},
  planned:     { label: "Planned",     symbol: "○", cls: "planned"    },
};

const STAGE_PRIORITY = [
  "qc_fail","failed","planned","not_started",
  "qc_warn","qc_pending","cmorised","qc_pass","published"
];

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

// ── App state ───────────────────────────────────────────────────────────────
let progress = null;
let currentView = "overview";

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
  document.getElementById("meta").textContent =
    `Generated ${new Date(progress.generated_at).toLocaleString()} · ` +
    `${totalUnits} units · ${done} cmorised or beyond`;

  renderView();
});

function renderView() {
  const app = document.getElementById("app");
  app.innerHTML = "";
  if (currentView === "overview")    renderOverview(app);
  if (currentView === "experiment")  renderExperimentDetail(app);
  if (currentView === "member")      renderMemberTimeline(app);
  if (currentView === "variable")    renderVariablePipeline(app);
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
  const s = STAGES[stage] || STAGES.not_started;
  return `<td class="cell-${s.cls}" title="${s.label}">${s.symbol}</td>`;
}

function stageBadge(stage) {
  const s = STAGES[stage] || STAGES.not_started;
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
    ["qc_pass",    summary.qc_pass    || 0, "seg-qc_pass"],
    ["qc_warn",    summary.qc_warn    || 0, "seg-qc_warn"],
    ["cmorised",   summary.cmorised   || 0, "seg-cmorised"],
    ["failed",     summary.failed     || 0, "seg-failed"],
    ["not_started",(summary.not_started || 0) + (summary.planned || 0), "seg-not_started"],
  ];
  const bars = segments
    .filter(([,n]) => n > 0)
    .map(([,n,cls]) => `<div class="progress-segment ${cls}" style="width:${(n/total*100).toFixed(1)}%" title="${n}"></div>`)
    .join("");
  return `<div class="progress-wrap">${bars}</div>`;
}

function derivedSummary(summary) {
  const published = summary.published || 0;
  const qcPass = summary.qc_pass || 0;
  const qcWarn = summary.qc_warn || 0;
  const qcFail = summary.qc_fail || 0;
  const cmorised = summary.cmorised || 0;
  const failed = summary.failed || 0;
  const planned = summary.planned || 0;
  const notStarted = summary.not_started || 0;

  return {
    published,
    qcComplete: published + qcPass,
    cmorisedComplete: published + qcPass + qcWarn + qcFail + cmorised,
    failed,
    pending: planned + notStarted,
  };
}

function countChips(summary) {
  const derived = derivedSummary(summary);
  const parts = [];
  const checks = [
    ["published", "seg-published", derived.published],
    ["qc✓", "seg-qc_pass", derived.qcComplete],
    ["cmorised", "seg-cmorised", derived.cmorisedComplete],
    ["failed", "seg-failed", derived.failed],
    ["pending", "seg-not_started", derived.pending],
  ];
  for (const [label, cls, n] of checks) {
    if (n) parts.push(`<span class="chip ${cls}" style="opacity:0.85">${n} ${label}</span>`);
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
  container.appendChild(el(makeLegend(["published","qc_pass","qc_warn","cmorised","failed","planned","not_started"])));

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
    const lnk = event.target.closest(".member-label");
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
  container.appendChild(el(makeLegend(["published","qc_pass","qc_warn","cmorised","failed","planned","not_started"])));

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
      th.innerHTML = `<span class="member-label variable-link" data-var="${escHtml(v)}">${variableLabelHtml(variableUnit)}</span>`;
      row.appendChild(th);
      for (const m of members) {
        const u = byKey[`${v}__${m}`];
        const stage = u ? u.pipeline_stage : "not_started";
        const s = STAGES[stage] || STAGES.not_started;
        row.insertCell().outerHTML = `<td class="cell-${s.cls}" title="${s.label} — ${v} / ${m}">${s.symbol}</td>`;
      }
    }
    scrollDiv.appendChild(table);
    wrap.appendChild(scrollDiv);

    // Wire variable links
    wrap.querySelectorAll("[data-var]").forEach(lnk => {
      lnk.style.cursor = "pointer";
      lnk.style.color = "#58a6ff";
      lnk.addEventListener("click", () => {
        document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
        document.querySelector('[data-view="variable"]').classList.add("active");
        currentView = "variable";
        renderVariablePipeline(document.getElementById("app"), lnk.dataset.var);
      });
    });
  }

  controls.querySelector("#sel-model").addEventListener("change", e => {
    selModel = e.target.value;
    selExp = experimentsForModel(selModel)[0];
    controls.querySelector("#sel-exp").innerHTML = buildOptions(experimentsForModel(selModel), selExp);
    redraw();
  });
  controls.querySelector("#sel-exp").addEventListener("change",   e => { selExp   = e.target.value; redraw(); });
  controls.querySelector("#var-filter").addEventListener("input",  e => { varFilter = e.target.value.trim(); redraw(); });

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
      STAGE_PRIORITY.indexOf(a.pipeline_stage) - STAGE_PRIORITY.indexOf(b.pipeline_stage)
    );

    const scrollDiv = document.createElement("div");
    scrollDiv.className = "scroll";
    const table = document.createElement("table");
    table.className = "detail";
    table.innerHTML = `<thead><tr><th>Variable</th><th>CMORisation</th><th>QC Checks</th><th>Publication</th></tr></thead>`;
    const tbody = document.createElement("tbody");
    for (const u of sorted) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${variableLabelHtml(u)}</td>
        <td>${simpleStatusBadge(cmorSimpleStatus(u))}</td>
        <td>${simpleStatusBadge(qcSimpleStatus(u))}</td>
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

  redraw();
}

// ── View: Variable Pipeline ──────────────────────────────────────────────────
function renderVariablePipeline(container, preVar) {
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

  const controls = document.createElement("div");
  controls.className = "controls";
  controls.innerHTML = `
    <label>Search</label>
    <input id="var-search" type="text" placeholder="e.g. Amon.tos or ocean.tos..." style="width:240px"/>
    <label>Variable</label>
    <select id="sel-var" style="max-width:200px">
      <option value="">— select —</option>
    </select>
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

  function redraw(variable) {
    wrap.innerHTML = "";
    if (!variable) return;
    const units = progress.units.filter(u => u.variable === variable);
    if (!units.length) {
      wrap.innerHTML = "<p style='color:var(--text-muted)'>No data for this variable.</p>";
      return;
    }

    const models     = [...new Set(units.map(u => u.model))].sort();
    const experiments= [...new Set(units.map(u => u.experiment))].sort();
    const members    = [...new Set(units.map(u => u.member))].sort();

    const byKey = {};
    for (const u of units) byKey[`${u.model}__${u.experiment}__${u.member}`] = u;

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
          const stage = u ? u.pipeline_stage : "not_started";
          const s = STAGES[stage] || STAGES.not_started;
          row.insertCell().outerHTML = `<td class="cell-${s.cls}" title="${s.label} — ${exp}/${m}">${s.symbol}</td>`;
        }
      }
    }

    scrollDiv.appendChild(table);
    wrap.appendChild(el(makeLegend(["published","qc_pass","qc_warn","cmorised","failed","planned","not_started"])));
    wrap.appendChild(scrollDiv);
  }

  const sel = controls.querySelector("#sel-var");
  refreshVariableOptions(preVar || "");
  if (preVar) redraw(preVar);
  controls.querySelector("#var-search").addEventListener("input", e => {
    varFilter = e.target.value.trim();
    const selected = sel.value;
    refreshVariableOptions(selected);
    if (sel.value !== selected) {
      wrap.innerHTML = "";
    }
  });
  sel.addEventListener("change", e => redraw(e.target.value));
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
