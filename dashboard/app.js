/**
 * ACCESS-MOPPy Submission Progress Dashboard
 * Reads progress.json compiled by scripts/compile_progress.py
 */

const PROGRESS_URL = "progress.json";
const GITHUB_REPO  = "rbeucher/access-moppy-progress";

// ── Stage metadata ──────────────────────────────────────────────────────────
const STAGES = {
  published:   { label: "Published",   symbol: "★", cls: "published"  },
  publishing:  { label: "Publishing",  symbol: "↑", cls: "publishing" },
  qc_pass:     { label: "QC Pass",     symbol: "✓", cls: "qc_pass"    },
  qc_warn:     { label: "QC Warn",     symbol: "!", cls: "qc_warn"    },
  qc_fail:     { label: "QC Fail",     symbol: "✗", cls: "qc_fail"    },
  qc_pending:  { label: "QC Pending",  symbol: "?", cls: "qc_pending" },
  cmorised:    { label: "CMORised",    symbol: "✓", cls: "cmorised"   },
  cmorising:   { label: "CMORising",   symbol: "⟳", cls: "cmorising"  },
  failed:      { label: "Failed",      symbol: "✗", cls: "failed"     },
  not_started: { label: "Not started", symbol: "·", cls: "not_started"},
  planned:     { label: "Planned",     symbol: "○", cls: "planned"    },
};

const STAGE_PRIORITY = [
  "qc_fail","failed","cmorising","planned","not_started",
  "qc_warn","qc_pending","cmorised","qc_pass","publishing","published"
];

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
  const done = progress.units.filter(u => ["published","qc_pass","cmorised"].includes(u.pipeline_stage)).length;
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

function progressBar(summary, total) {
  if (!total) return "";
  const segments = [
    ["published",  summary.published  || 0, "seg-published"],
    ["publishing", summary.publishing || 0, "seg-publishing"],
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

function countChips(summary) {
  const parts = [];
  const checks = [
    ["published",  "seg-published",  summary.published],
    ["qc✓",       "seg-qc_pass",    summary.qc_pass],
    ["cmorised",   "seg-cmorised",   summary.cmorised],
    ["failed",     "seg-failed",     summary.failed],
    ["pending",    "seg-not_started",(summary.not_started||0)+(summary.planned||0)],
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
  container.appendChild(el(makeLegend(["published","publishing","qc_pass","qc_warn","cmorised","failed","not_started"])));

  const models = progress.models;
  for (const model of models) {
    const modelHead = h("div", "view-title", model);
    modelHead.style.cssText = "font-size:0.9rem;margin-top:1.5rem;margin-bottom:0.75rem;";
    container.appendChild(modelHead);

    const grid = document.createElement("div");
    grid.className = "overview-grid";

    const expIndex = progress.index[model]?.experiments || {};
    for (const [expId, expInfo] of Object.entries(expIndex)) {
      const members = expInfo.members || [];
      const card = document.createElement("div");
      card.className = "exp-card";

      const priority = expInfo.priority || "medium";
      card.innerHTML = `
        <h3>${expId} <span style="font-size:0.7rem;color:var(--text-muted);font-weight:400">${priority}</span></h3>
        <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.5rem">${members.length} member${members.length!==1?"s":""}</div>
      `;

      const table = document.createElement("table");
      table.className = "members-table";
      table.innerHTML = `<thead><tr><th>Member</th><th>Progress</th><th>Breakdown</th></tr></thead>`;
      const tbody = document.createElement("tbody");

      for (const member of members) {
        const key = `${model}/${expId}/${member}`;
        const summary = progress.summaries[key] || {};
        const total = summary.total_planned || 1;
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><span class="member-label" data-model="${model}" data-exp="${expId}" data-member="${member}">${member}</span></td>
          <td>${progressBar(summary, total)}<span style="font-size:0.7rem;color:var(--text-muted)">${total}</span></td>
          <td>${countChips(summary)}</td>
        `;
        tbody.appendChild(tr);
      }

      table.appendChild(tbody);
      card.appendChild(table);
      grid.appendChild(card);
    }
    container.appendChild(grid);
  }

  // Wire member links to member timeline view
  container.querySelectorAll(".member-label").forEach(lnk => {
    lnk.addEventListener("click", () => {
      document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
      document.querySelector('[data-view="member"]').classList.add("active");
      currentView = "member";
      renderMemberTimeline(document.getElementById("app"), lnk.dataset.model, lnk.dataset.exp, lnk.dataset.member);
    });
  });
}

// ── View: Experiment Detail ──────────────────────────────────────────────────
function renderExperimentDetail(container, preModel, preExp) {
  container.innerHTML = "";
  const models = progress.models;
  const allExps = [...new Set(progress.units.map(u => u.experiment))].sort();

  let selModel = preModel || models[0];
  let selExp   = preExp   || allExps[0];

  const controls = document.createElement("div");
  controls.className = "controls";
  controls.innerHTML = `
    <label>Model</label>
    <select id="sel-model">${models.map(m => `<option${m===selModel?" selected":""}>${m}</option>`).join("")}</select>
    <label>Experiment</label>
    <select id="sel-exp">${allExps.map(e => `<option${e===selExp?" selected":""}>${e}</option>`).join("")}</select>
    <label>Filter variable</label>
    <input id="var-filter" type="text" placeholder="e.g. tas" style="width:110px"/>
  `;

  const title = h("div", "view-title", "Experiment Detail");
  const sub   = h("div", "view-sub", "Rows = variables · Columns = ensemble members · Click a cell for details.");
  container.appendChild(title);
  container.appendChild(sub);
  container.appendChild(controls);
  container.appendChild(el(makeLegend(["published","publishing","qc_pass","qc_warn","cmorised","cmorising","failed","not_started"])));

  const wrap = document.createElement("div");
  container.appendChild(wrap);

  let varFilter = "";

  function redraw() {
    wrap.innerHTML = "";
    const units = unitsFor(selModel, selExp, null);
    const members = [...new Set(units.map(u => u.member))].sort();
    let variables = [...new Set(units.map(u => u.variable))].sort();
    if (varFilter) variables = variables.filter(v => v.includes(varFilter));
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
    for (const v of variables) {
      const row = tbody.insertRow();
      const th = document.createElement("th");
      th.innerHTML = `<span class="member-label" data-var="${v}">${v}</span>`;
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

  controls.querySelector("#sel-model").addEventListener("change", e => { selModel = e.target.value; redraw(); });
  controls.querySelector("#sel-exp").addEventListener("change",   e => { selExp   = e.target.value; redraw(); });
  controls.querySelector("#var-filter").addEventListener("input",  e => { varFilter = e.target.value.trim(); redraw(); });

  redraw();
}

// ── View: Member Timeline ────────────────────────────────────────────────────
function renderMemberTimeline(container, preModel, preExp, preMember) {
  container.innerHTML = "";

  const models   = progress.models;
  const allExps  = [...new Set(progress.units.map(u => u.experiment))].sort();
  const allMembers = [...new Set(progress.units.map(u => u.member))].sort();

  let selModel  = preModel  || models[0];
  let selExp    = preExp    || allExps[0];
  let selMember = preMember || allMembers[0];

  const controls = document.createElement("div");
  controls.className = "controls";
  controls.innerHTML = `
    <label>Model</label>
    <select id="sel-model">${models.map(m => `<option${m===selModel?" selected":""}>${m}</option>`).join("")}</select>
    <label>Experiment</label>
    <select id="sel-exp">${allExps.map(e => `<option${e===selExp?" selected":""}>${e}</option>`).join("")}</select>
    <label>Member</label>
    <select id="sel-member">${allMembers.map(m => `<option${m===selMember?" selected":""}>${m}</option>`).join("")}</select>
  `;

  const title = h("div", "view-title", "Member Timeline");
  const sub   = h("div", "view-sub", "All variables for a single (model, experiment, member) — ordered by pipeline stage.");
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
    table.innerHTML = `<thead><tr><th>Variable</th><th>Pipeline Stage</th><th>CMORisation</th><th>Publication</th></tr></thead>`;
    const tbody = document.createElement("tbody");
    for (const u of sorted) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code>${escHtml(u.variable)}</code></td>
        <td>${stageBadge(u.pipeline_stage)}</td>
        <td>${stageBadge(u.cmorisation_status)}</td>
        <td>${stageBadge(u.publication_status)}</td>
      `;
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    scrollDiv.appendChild(table);
    wrap.appendChild(scrollDiv);
  }

  controls.querySelector("#sel-model").addEventListener("change",  e => { selModel  = e.target.value; redraw(); });
  controls.querySelector("#sel-exp").addEventListener("change",    e => { selExp    = e.target.value; redraw(); });
  controls.querySelector("#sel-member").addEventListener("change", e => { selMember = e.target.value; redraw(); });

  redraw();
}

// ── View: Variable Pipeline ──────────────────────────────────────────────────
function renderVariablePipeline(container, preVar) {
  container.innerHTML = "";

  const allVars = [...new Set(progress.units.map(u => u.variable))].sort();

  const controls = document.createElement("div");
  controls.className = "controls";
  controls.innerHTML = `
    <label>Variable</label>
    <select id="sel-var" style="max-width:200px">
      <option value="">— select —</option>
      ${allVars.map(v => `<option value="${v}"${v===preVar?" selected":""}>${v}</option>`).join("")}
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
    wrap.appendChild(el(makeLegend(["published","publishing","qc_pass","qc_warn","cmorised","cmorising","failed","not_started"])));
    wrap.appendChild(scrollDiv);
  }

  const sel = controls.querySelector("#sel-var");
  if (preVar) redraw(preVar);
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
