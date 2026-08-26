#!/usr/bin/env python3
"""
compile_progress.py
===================

Reads all plans/*.yaml and progress/**/*.json and produces a single
dashboard/progress.json consumed by the dashboard.

Usage
-----
    python scripts/compile_progress.py [--output PATH]

Output schema
-------------
{
  "generated_at": "<ISO-8601 UTC>",
  "models": ["ACCESS-ESM1.6", ...],
  "plans": {
    "<model>": {
      "experiments": [
        {
          "id": "historical",
          "members": ["r1i1p1f1", ...],
          "target_variables": [...] | "*"
        }
      ]
    }
  },
  "units": [
    {
      "model":                 "ACCESS-ESM1.6",
      "experiment":            "historical",
      "member":                "r1i1p1f1",
      "variable":              "tas",
      "state":                 "cmorised",
      "gates":                 {"range": "not_run", "wcrp": "not_run", "repack": "implied"},
      "gates_cleared":         1,
      "cmorisation_status":    "completed",
      "publication_status":    "not_published"
    }
  ],
  "summaries": {
    "ACCESS-ESM1.6/historical/r1i1p1f1": {
      "total_planned":    115,
      "planned":            0,
      "cmorise_failed":     5,
      "cmorised":         110,
      "blocked":            0,
      "ready_for_review":   0,
      "published":          0,
      "gates": {
        "range":  {"pass": 0, "warn": 0, "fail": 0, "implied": 0,   "not_run": 110},
        "wcrp":   {"pass": 0, "warn": 0, "fail": 0, "implied": 0,   "not_run": 110},
        "repack": {"pass": 0, "warn": 0, "fail": 0, "implied": 110, "not_run": 0}
      }
    }
  }
}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
VARIABLE_METADATA_PATH = ROOT / "data" / "variable_metadata.json"

_MEMBER_RE = re.compile(r"^r(\d+)i(\d+)p(\d+)f(\d+)$")


def _member_sort_key(member: str) -> tuple:
    """Natural sort key so r2i1p1f1 sorts before r10i1p1f1."""
    match = _MEMBER_RE.match(member)
    if match:
        return (0, tuple(int(g) for g in match.groups()))
    return (1, member)

# ── Release gate helpers ────────────────────────────────────────────────────

# A CMORised variable is a candidate, not a result. Three checks decide whether
# it can be handed to CSIRO for scientific review and to NCI for publication.
# The order is fixed — the dashboard draws them as a three-segment strip and
# segment position is what makes the strip readable without a legend.
GATES = ("range", "wcrp", "repack")

# Outcomes that count as cleared. "implied" is cleared but not evidenced: see
# _repack_is_implied.
GATE_CLEARED = ("pass", "warn", "implied")

GATE_RESULTS = ("pass", "warn", "fail", "implied", "not_run")

# Worst first, for rolling many variables up into one member-level gate. An
# unrun check outranks a warning: not knowing is worse than knowing and being
# mildly unhappy.
GATE_PRIORITY = ("fail", "not_run", "warn", "implied", "pass")

# Every state here has a producer. That is the point: the retired qc_pass /
# qc_warn / qc_fail / qc_pending stages had none, so the dashboard advertised
# a QC pipeline that could never report anything.
STATES = (
    "planned",
    "cmorise_failed",
    "cmorised",
    "blocked",
    "ready_for_review",
    "published",
)

CMOR_STATUS_PRIORITY = {
    "failed": 0,
    "running": 1,
    "retrying": 1,
    "pending": 1,
    "completed": 2,
}

PUBLICATION_STATUS_PRIORITY = {
    "not_published": 0,
    "publishing": 1,
    "published": 2,
    "retracted": 0,
}


def _repack_is_implied(plan: dict | None) -> bool:
    """Whether a completed CMORisation task implies its output was repacked.

    ACCESS-MOPPy runs ``cmip7repack`` inline for CMIP7 output and a repack
    failure aborts the task, so "task completed" does imply "repacked" — but
    nothing is written down, so this is an inference and not evidence. The
    dashboard marks it as such, and any recorded result overrides it.
    """
    return bool(plan) and plan.get("mip_era") == "CMIP7"


def _gate_results(
    entry: dict | None,
    cmor_status: str | None,
    repack_implied: bool,
) -> dict[str, str]:
    """Resolve the three gates for one variable.

    Gates only mean anything once CMORisation has completed; before that they
    are all ``not_run`` rather than absent, so the dashboard can show that a
    check has not happened as clearly as it shows a failure.
    """
    gates = dict.fromkeys(GATES, "not_run")
    if cmor_status != "completed":
        return gates
    if repack_implied:
        gates["repack"] = "implied"
    for gate in GATES:
        recorded = (entry or {}).get(gate)
        if not isinstance(recorded, dict):
            continue
        result = recorded.get("result")
        if result in GATE_RESULTS:
            gates[gate] = result
    return gates


def _gate_message(gate: str, recorded: dict | None) -> str | None:
    """One-line evidence for a gate, shown on hover in the dashboard."""
    if not isinstance(recorded, dict):
        return None
    if recorded.get("message"):
        return str(recorded["message"])
    observed, allowed = recorded.get("observed"), recorded.get("allowed")
    if gate == "range" and observed and allowed:
        units = f" {recorded['units']}" if recorded.get("units") else ""
        return (
            f"observed {observed[0]:g}…{observed[1]:g}{units}, "
            f"allowed {allowed[0]:g}…{allowed[1]:g}{units}"
        )
    if gate == "wcrp" and recorded.get("cv_version"):
        suites = ", ".join(recorded.get("suites", [])) or "default suites"
        return f"{suites} · {recorded['cv_version']}"
    return None


def _unit_state(
    cmor_status: str | None,
    gates: dict[str, str],
    pub_status: str | None,
) -> str:
    """Derive a single state from CMORisation, the gates, and publication."""
    if pub_status == "published":
        return "published"
    if cmor_status is None or cmor_status == "not_started":
        return "planned"
    if cmor_status == "failed":
        return "cmorise_failed"
    if cmor_status != "completed":
        # pending / running / retrying — in flight, nothing to show yet.
        return "planned"
    if any(result == "fail" for result in gates.values()):
        return "blocked"
    if all(result in GATE_CLEARED for result in gates.values()):
        return "ready_for_review"
    return "cmorised"


def _merge_cmor_status(current: str | None, new: str | None) -> str | None:
    """Return the most conservative CMOR status across duplicates."""
    if current is None:
        return new
    if new is None:
        return current
    return current if CMOR_STATUS_PRIORITY.get(current, -1) <= CMOR_STATUS_PRIORITY.get(new, -1) else new


def _merge_publication_status(current: str | None, new: str | None) -> str | None:
    """Return the furthest publication status seen across duplicates."""
    if current is None:
        return new
    if new is None:
        return current
    return current if PUBLICATION_STATUS_PRIORITY.get(current, -1) >= PUBLICATION_STATUS_PRIORITY.get(new, -1) else new


def _effective_publication_status(cmor_status: str | None, pub_status: str | None) -> str:
    """Publication cannot outrun CMOR completion."""
    if cmor_status != "completed":
        return "not_published"
    return pub_status or "not_published"


def _derive_frequency(cmip7_name: str | None) -> str | None:
    """Extract the frequency segment from a branded variable name.

    Branded names follow realm.variable.cell_methods.frequency.region
    (e.g. "atmos.tas.tavg-h2m-hxy-u.mon.glb" -> "mon").
    """
    if not cmip7_name:
        return None
    parts = cmip7_name.split(".")
    return parts[-2] if len(parts) >= 2 else None


# ── Loader helpers ───────────────────────────────────────────────────────────

def _load_plans() -> dict[str, dict]:
    """Return {model: plan_dict} for all plans/*.yaml files."""
    plans: dict[str, dict] = {}
    for yaml_file in sorted((ROOT / "plans").glob("*.yaml")):
        with yaml_file.open() as fh:
            plan = yaml.safe_load(fh)
        if plan and "model" in plan:
            plans[plan["model"]] = plan
    return plans


def _load_variable_metadata() -> dict[str, dict]:
    """Return {request_name: metadata_dict} for variable hover/display metadata."""
    if not VARIABLE_METADATA_PATH.exists():
        return {}
    with VARIABLE_METADATA_PATH.open() as fh:
        return json.load(fh)


def _load_requests() -> list[dict]:
    """Return request records from requests/*.yaml with their source file attached."""
    requests: list[dict] = []
    for yaml_file in sorted((ROOT / "requests").glob("*.yaml")):
        with yaml_file.open() as fh:
            req = yaml.safe_load(fh) or {}
        if not isinstance(req, dict):
            continue
        req["_request_file"] = str(yaml_file.relative_to(ROOT))
        requests.append(req)
    return requests


def _load_cmorisation(progress_root: Path) -> dict[tuple[str, str, str], dict]:
    """
    Scan progress/<model>/<exp>/<member>/cmorisation.json.
    Returns {(model, experiment, member): report_dict}.
    """
    reports: dict[tuple[str, str, str], dict] = {}
    for report_path in sorted(progress_root.rglob("cmorisation.json")):
        parts = report_path.relative_to(progress_root).parts
        if len(parts) != 4:
            continue
        model, exp, member, _ = parts
        with report_path.open() as fh:
            report = json.load(fh)
        reports[(model, exp, member)] = report
    return reports


def _load_publications(progress_root: Path) -> dict[tuple[str, str, str], dict]:
    """
    Scan progress/<model>/<exp>/<member>/publication.json.
    Returns {(model, experiment, member): pub_dict}.
    """
    pubs: dict[tuple[str, str, str], dict] = {}
    for pub_path in sorted(progress_root.rglob("publication.json")):
        parts = pub_path.relative_to(progress_root).parts
        if len(parts) != 4:
            continue
        model, exp, member, _ = parts
        with pub_path.open() as fh:
            pub = json.load(fh)
        pubs[(model, exp, member)] = pub
    return pubs


def _load_qc(progress_root: Path) -> dict[tuple[str, str, str], dict]:
    """
    Scan progress/<model>/<exp>/<member>/qc.json.
    Returns {(model, experiment, member): qc_dict}.
    """
    records: dict[tuple[str, str, str], dict] = {}
    for qc_path in sorted(progress_root.rglob("qc.json")):
        parts = qc_path.relative_to(progress_root).parts
        if len(parts) != 4:
            continue
        model, exp, member, _ = parts
        with qc_path.open() as fh:
            records[(model, exp, member)] = json.load(fh)
    return records


def _build_cmip7_lookup(plans: dict[str, dict]) -> dict[str, dict[str, str | None]]:
    """
    Return {cmip7_name (branded variable name): {request_name, short_name, cmip7_name}}
    collected from every plan's target_variables lists.

    Reports identify variables by their CMIP7 branded name (e.g.
    ``atmos.tas.tavg-h2m-hxy-u.mon.glb``), while plans/dashboard units are
    keyed by the CMIP6-style compound request name (e.g. ``Amon.tas``). This
    lookup lets us translate a report's branded name back to the request
    name it corresponds to.
    """
    lookup: dict[str, dict[str, str | None]] = {}
    for plan in plans.values():
        for exp_def in plan.get("experiments", []):
            target_variables = exp_def.get("target_variables", "*")
            if not isinstance(target_variables, list):
                continue
            for item in target_variables:
                if not isinstance(item, dict):
                    continue
                cmip7_name = item.get("cmip7_name")
                if not cmip7_name or cmip7_name in lookup:
                    continue
                lookup[cmip7_name] = {
                    "request_name": item["request_name"],
                    "short_name": item["short_name"],
                    "cmip7_name": cmip7_name,
                }
    return lookup


def _resolve_variables(target_variables: list | str, cmor_report: dict | None) -> list[str]:
    """
    Resolve target_variables (may be '*' or a list) to a concrete list.
    When '*', fall back to the variables that appear in the batch report tasks.
    """
    if target_variables != "*":
        return list(target_variables)
    if cmor_report:
        seen = {t["variable"] for t in cmor_report.get("tasks", [])}
        return sorted(seen)
    return []


def _normalize_target_variables(
    target_variables: list | str,
    cmor_report: dict | None,
    cmip7_lookup: dict[str, dict[str, str | None]],
) -> list[dict[str, str | None]]:
    """Return canonical variable metadata for planned variables.

    String entries (from '*' / report-derived resolution) are branded
    variable names from the report; translate them back to their
    request/short name via cmip7_lookup when known.
    """
    resolved = _resolve_variables(target_variables, cmor_report)
    normalized: list[dict[str, str | None]] = []
    for item in resolved:
        if isinstance(item, str):
            mapped = cmip7_lookup.get(item)
            if mapped:
                normalized.append(dict(mapped))
                continue
            parts = item.split(".")
            short_name = parts[1] if len(parts) > 1 else item
            normalized.append({
                "request_name": item,
                "short_name": short_name,
                "cmip7_name": item,
            })
            continue
        normalized.append({
            "request_name": item["request_name"],
            "short_name": item["short_name"],
            "cmip7_name": item.get("cmip7_name"),
        })
    return normalized


def _compile_unit_summary(
    model: str,
    exp_id: str,
    member: str,
    target_variables: list | str,
    cmor: dict | None,
    pub: dict | None,
    qc: dict | None,
    repack_implied: bool,
    variable_metadata: dict[str, dict],
    cmip7_lookup: dict[str, dict[str, str | None]],
) -> tuple[list[dict], dict] | None:
    """Build the unit list and summary dict for one (model, experiment, member).

    Returns None if there is nothing planned and nothing reported.
    """
    # Build per-variable cmor lookup. Report tasks are keyed by CMIP7
    # branded variable name (e.g. "atmos.tas.tavg-h2m-hxy-u.mon.glb"), not
    # the plan's request_name/short_name.
    cmor_by_branded: dict[str, str] = {}
    if cmor:
        for task in cmor.get("tasks", []):
            branded = task["variable"]
            cmor_by_branded[branded] = _merge_cmor_status(
                cmor_by_branded.get(branded),
                task["status"],
            )

    # Gate results are keyed by branded variable name where available, but a
    # record written by hand may use the request name or short name instead.
    qc_by_var: dict[str, dict] = dict((qc or {}).get("variables", {}))

    # Build per-variable publication lookup
    pub_by_var: dict[str, str] = {}
    if pub:
        for var, info in pub.get("variables", {}).items():
            pub_by_var[var] = _merge_publication_status(
                pub_by_var.get(var),
                info.get("status", "not_published"),
            )

    target_vars = _normalize_target_variables(target_variables, cmor, cmip7_lookup)

    if not target_vars and not cmor_by_branded:
        return None

    planned_branded_names = {v["cmip7_name"] for v in target_vars if v.get("cmip7_name")}
    extra_report_vars = [
        cmip7_lookup.get(branded, {
            "request_name": branded,
            "short_name": branded.split(".")[1] if branded.count(".") > 1 else branded,
            "cmip7_name": branded,
        })
        for branded in sorted(cmor_by_branded.keys())
        if branded not in planned_branded_names
    ]
    all_vars = target_vars + extra_report_vars

    summary: dict = {"total_planned": len(all_vars)}
    summary.update(dict.fromkeys(STATES, 0))
    summary["gates"] = {
        gate: dict.fromkeys(GATE_RESULTS, 0) for gate in GATES
    }

    units: list[dict] = []
    for var in all_vars:
        request_name = str(var["request_name"])
        short_name = str(var["short_name"])
        cmip7_name = var.get("cmip7_name")
        metadata = variable_metadata.get(request_name, {})
        cmor_status = None
        if cmip7_name:
            cmor_status = cmor_by_branded.get(cmip7_name)
        if cmor_status is None:
            cmor_status = cmor_by_branded.get(request_name) or cmor_by_branded.get(short_name)
        pub_status = _effective_publication_status(
            cmor_status,
            pub_by_var.get(short_name, pub_by_var.get(request_name)),
        )

        qc_entry = None
        for key in (cmip7_name, request_name, short_name):
            if key and key in qc_by_var:
                qc_entry = qc_by_var[key]
                break

        gates = _gate_results(qc_entry, cmor_status, repack_implied)
        state = _unit_state(cmor_status, gates, pub_status)

        unit = {
            "model": model,
            "experiment": exp_id,
            "member": member,
            "variable": cmip7_name or request_name,
            "variable_short": short_name,
            "variable_cmip7": cmip7_name,
            "variable_frequency": _derive_frequency(cmip7_name),
            "variable_description": metadata.get("description"),
            "variable_notes": metadata.get("notes"),
            "state": state,
            "gates": gates,
            "gates_cleared": sum(1 for r in gates.values() if r in GATE_CLEARED),
            "cmorisation_status": cmor_status or "not_started",
            "publication_status": pub_status,
        }

        messages = {
            gate: message
            for gate in GATES
            if (message := _gate_message(gate, (qc_entry or {}).get(gate)))
        }
        if messages:
            unit["gate_messages"] = messages

        units.append(unit)

        summary[state] = summary.get(state, 0) + 1
        # Gates are only counted where they mean something — a variable that
        # never CMORised has nothing to check.
        if cmor_status == "completed":
            for gate, result in gates.items():
                summary["gates"][gate][result] += 1

    return units, summary


# ── Main compilation ─────────────────────────────────────────────────────────

def compile_progress(output: Path) -> None:
    plans = _load_plans()
    variable_metadata = _load_variable_metadata()
    cmip7_lookup = _build_cmip7_lookup(plans)
    request_records = _load_requests()
    progress_root = ROOT / "progress"
    cmor_reports = _load_cmorisation(progress_root)
    pub_reports   = _load_publications(progress_root)
    qc_records    = _load_qc(progress_root)

    all_units: list[dict] = []
    summaries: dict[str, dict] = {}
    covered_keys: set[tuple[str, str, str]] = set()

    for model, plan in plans.items():
        for exp_def in plan.get("experiments", []):
            exp_id = exp_def["id"]
            for member_def in exp_def.get("members", []):
                member = member_def["variant_label"]
                key = (model, exp_id, member)
                covered_keys.add(key)

                result = _compile_unit_summary(
                    model, exp_id, member,
                    exp_def.get("target_variables", "*"),
                    cmor_reports.get(key), pub_reports.get(key),
                    qc_records.get(key), _repack_is_implied(plan),
                    variable_metadata, cmip7_lookup,
                )
                if result is None:
                    continue
                units, summary = result
                all_units.extend(units)
                summaries[f"{model}/{exp_id}/{member}"] = summary

    # Surface any reports for (model, experiment, member) combinations that
    # are not declared in a plan yet — e.g. ensemble members ingested ahead
    # of the plan being updated. Treated the same as planned combos so they
    # show up in the index/summaries the dashboard reads, not just in units.
    report_keys = set(cmor_reports.keys()) | set(pub_reports.keys()) | set(qc_records.keys())
    for key in sorted(report_keys - covered_keys):
        model, exp_id, member = key
        result = _compile_unit_summary(
            model, exp_id, member, "*",
            cmor_reports.get(key), pub_reports.get(key),
            qc_records.get(key), _repack_is_implied(plans.get(model)),
            variable_metadata, cmip7_lookup,
        )
        if result is None:
            continue
        units, summary = result
        for unit in units:
            unit["_orphan"] = True
        all_units.extend(units)
        summaries[f"{model}/{exp_id}/{member}"] = summary
        covered_keys.add(key)

    # Build model/experiment/member index for quick nav
    index: dict[str, dict] = {}
    planned_request_keys: set[tuple[str, str, str]] = set()
    for plan_model, plan in plans.items():
        index[plan_model] = {"experiments": {}}
        for exp_def in plan.get("experiments", []):
            eid = exp_def["id"]
            members = [m["variant_label"] for m in exp_def.get("members", [])]
            for member in members:
                planned_request_keys.add((plan_model, eid, member))
            index[plan_model]["experiments"][eid] = {
                "members": members,
                "priority": exp_def.get("priority", "medium"),
                "deck": exp_def.get("deck", False),
                "label": exp_def.get("label", eid),
                "theme": exp_def.get("theme", "deck" if exp_def.get("deck", False) else "default"),
                "category": exp_def.get("category"),
                "tags": exp_def.get("tags", []),
            }

    # Extend the index with any members observed only through reports (not
    # yet listed in a plan), so the Overview/Member views can see them too.
    observed: dict[tuple[str, str], set[str]] = {}
    for model, exp_id, member in covered_keys:
        observed.setdefault((model, exp_id), set()).add(member)

    for (model, exp_id), members_seen in observed.items():
        model_entry = index.setdefault(model, {"experiments": {}})
        exp_entry = model_entry["experiments"].setdefault(exp_id, {
            "members": [],
            "priority": "medium",
            "deck": False,
            "label": exp_id,
            "theme": "default",
            "category": None,
            "tags": [],
        })
        already_listed = set(exp_entry["members"])
        extra = sorted(members_seen - already_listed, key=_member_sort_key)
        if extra:
            exp_entry["members"] = exp_entry["members"] + extra

    compiled_requests: list[dict] = []
    request_keys: set[tuple[str, str, str]] = set()
    for req in request_records:
        model = req.get("model")
        exp_id = req.get("experiment_id")
        member = req.get("variant_label")
        if not all((model, exp_id, member)):
            continue

        key = (str(model), str(exp_id), str(member))
        request_keys.add(key)
        summary_key = "/".join(key)
        summary = summaries.get(summary_key)
        target_variables = req.get("target_variables", "*")
        if isinstance(target_variables, list):
            target_variable_count = len(target_variables)
            target_variable_mode = "subset"
        else:
            target_variable_count = None
            target_variable_mode = "all"

        compiled_requests.append({
            "model": model,
            "source_id": req.get("source_id"),
            "experiment": exp_id,
            "member": member,
            "status": req.get("status", "proposed"),
            "priority": req.get("priority", "medium"),
            "contact": req.get("contact"),
            "requested_by": req.get("requested_by"),
            "requested_at": req.get("requested_at"),
            "accepted_at": req.get("accepted_at"),
            "issue": req.get("issue"),
            "request_file": req.get("_request_file"),
            "gadi": {
                "project": req.get("gadi", {}).get("project"),
                "input_folder": req.get("gadi", {}).get("input_folder"),
                "output_folder": req.get("gadi", {}).get("output_folder"),
            },
            "cmip_metadata": req.get("cmip_metadata", {}),
            "run_dates": req.get("run_dates", {}),
            "target_variables_mode": target_variable_mode,
            "target_variable_count": target_variable_count,
            "notes": req.get("notes"),
            "in_plan": key in planned_request_keys,
            "progress_summary": summary,
        })

    request_gaps = [
        {
            "model": model,
            "experiment": exp,
            "member": member,
            "label": index.get(model, {}).get("experiments", {}).get(exp, {}).get("label", exp),
        }
        for (model, exp, member) in sorted(planned_request_keys - request_keys)
    ]

    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "models": sorted(index.keys()),
        "index": index,
        "summaries": summaries,
        "units": all_units,
        "requests": compiled_requests,
        "request_gaps": request_gaps,
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    ready = sum(1 for unit in all_units if unit["state"] == "ready_for_review")
    checked = sum(
        1 for unit in all_units
        if any(result not in ("not_run", "implied") for result in unit["gates"].values())
    )
    print(
        f"Progress compiled: {len(all_units)} units across "
        f"{len(summaries)} (model, experiment, member) combinations → {output}"
    )
    print(
        f"  Release gates: {checked} units with a recorded gate result, "
        f"{ready} ready for review"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile progress.json from plans + reports")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dashboard" / "progress.json",
        help="Output path (default: dashboard/progress.json)",
    )
    args = parser.parse_args()
    try:
        compile_progress(args.output)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
