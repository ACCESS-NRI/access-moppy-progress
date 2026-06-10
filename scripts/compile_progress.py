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
      "pipeline_stage":        "qc_pass",
      "cmorisation_status":    "completed",
      "publication_status":    "not_published"
    }
  ],
  "summaries": {
    "ACCESS-ESM1.6/historical/r1i1p1f1": {
      "total_planned":  115,
      "cmorised":       110,
      "cmorised_partial": 0,
      "qc_pass":          0,
      "qc_warn":          0,
      "qc_fail":          0,
      "published":        0,
      "failed":           5,
      "not_started":      0
    }
  }
}
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
VARIABLE_METADATA_PATH = ROOT / "data" / "variable_metadata.json"

# ── Pipeline stage helpers ──────────────────────────────────────────────────

# Priority order: highest-concern first (used for aggregation)
STAGE_PRIORITY = [
    "qc_fail",
    "cmorised_partial",
    "failed",
    "planned",
    "not_started",
    "qc_warn",
    "qc_pending",
    "cmorised",
    "qc_pass",
    "published",
]

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


def _pipeline_stage(
    cmor_status: str | None,
    pub_status: str | None,
) -> str:
    """Derive a single pipeline_stage string from component statuses."""
    if cmor_status is None:
        return "planned"
    if cmor_status == "running":
        return "planned"
    if cmor_status == "failed":
        return "failed"
    if cmor_status == "completed":
        if pub_status == "published":
            return "published"
        return "cmorised"
    # pending/retrying
    return "planned"


def _aggregate_stage(stages: list[str]) -> str:
    """Return worst-case stage across a set of stages."""
    if not stages:
        return "not_started"
    return min(stages, key=lambda s: STAGE_PRIORITY.index(s) if s in STAGE_PRIORITY else 999)


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
) -> list[dict[str, str | None]]:
    """Return canonical variable metadata for planned variables."""
    resolved = _resolve_variables(target_variables, cmor_report)
    normalized: list[dict[str, str | None]] = []
    for item in resolved:
        if isinstance(item, str):
            normalized.append({
                "request_name": item,
                "short_name": item.split(".")[-1],
                "cmip7_name": None,
            })
            continue
        normalized.append({
            "request_name": item["request_name"],
            "short_name": item["short_name"],
            "cmip7_name": item.get("cmip7_name"),
        })
    return normalized


# ── Main compilation ─────────────────────────────────────────────────────────

def compile_progress(output: Path) -> None:
    plans = _load_plans()
    variable_metadata = _load_variable_metadata()
    progress_root = ROOT / "progress"
    cmor_reports = _load_cmorisation(progress_root)
    pub_reports   = _load_publications(progress_root)

    all_units: list[dict] = []
    summaries: dict[str, dict] = {}

    for model, plan in plans.items():
        for exp_def in plan.get("experiments", []):
            exp_id = exp_def["id"]
            for member_def in exp_def.get("members", []):
                member = member_def["variant_label"]
                key = (model, exp_id, member)

                cmor = cmor_reports.get(key)
                pub  = pub_reports.get(key)

                # Build per-variable cmor lookup
                cmor_by_var: dict[str, str] = {}
                if cmor:
                    for task in cmor.get("tasks", []):
                        short_name = task["variable"]
                        cmor_by_var[short_name] = _merge_cmor_status(
                            cmor_by_var.get(short_name),
                            task["status"],
                        )

                # Build per-variable publication lookup
                pub_by_var: dict[str, str] = {}
                if pub:
                    for var, info in pub.get("variables", {}).items():
                        pub_by_var[var] = _merge_publication_status(
                            pub_by_var.get(var),
                            info.get("status", "not_published"),
                        )

                # Resolve target variables
                target_vars = _normalize_target_variables(
                    exp_def.get("target_variables", "*"), cmor
                )

                # If no plan variables and no report, skip
                if not target_vars and not cmor_by_var:
                    continue

                planned_short_names = {v["short_name"] for v in target_vars}
                extra_report_vars = [
                    {
                        "request_name": short_name,
                        "short_name": short_name,
                        "cmip7_name": None,
                    }
                    for short_name in sorted(cmor_by_var.keys())
                    if short_name not in planned_short_names
                ]
                all_vars = target_vars + extra_report_vars

                summary: dict[str, int] = {
                    "total_planned": len(all_vars),
                    "cmorised": 0, "cmorised_partial": 0,
                    "qc_pass": 0, "qc_warn": 0, "qc_fail": 0,
                    "published": 0, "failed": 0, "planned": 0, "not_started": 0,
                }

                for var in all_vars:
                    request_name = str(var["request_name"])
                    short_name = str(var["short_name"])
                    cmip7_name = var.get("cmip7_name")
                    metadata = variable_metadata.get(request_name, {})
                    cmor_status = cmor_by_var.get(short_name) or cmor_by_var.get(request_name)
                    pub_status = _effective_publication_status(
                        cmor_status,
                        pub_by_var.get(short_name, pub_by_var.get(request_name)),
                    )

                    stage = _pipeline_stage(cmor_status, pub_status)

                    unit = {
                        "model": model,
                        "experiment": exp_id,
                        "member": member,
                        "variable": request_name,
                        "variable_short": short_name,
                        "variable_cmip7": cmip7_name,
                        "variable_description": metadata.get("description"),
                        "variable_notes": metadata.get("notes"),
                        "pipeline_stage": stage,
                        "cmorisation_status": cmor_status or "not_started",
                        "publication_status": pub_status,
                    }
                    all_units.append(unit)

                    key_s = stage if stage in summary else "not_started"
                    summary[key_s] = summary.get(key_s, 0) + 1

                summaries[f"{model}/{exp_id}/{member}"] = summary

    # Also surface any reports that are NOT in a plan (orphans)
    for (model, exp, member), cmor in cmor_reports.items():
        if not any(
            u["model"] == model and u["experiment"] == exp and u["member"] == member
            for u in all_units
        ):
            pub = pub_reports.get((model, exp, member), {})
            pub_by_var: dict[str, str] = {}
            for var, info in pub.get("variables", {}).items():
                pub_by_var[var] = _merge_publication_status(
                    pub_by_var.get(var),
                    info.get("status", "not_published"),
                )
            for task in cmor.get("tasks", []):
                var = task["variable"]
                pub_status = _effective_publication_status(task["status"], pub_by_var.get(var))
                stage = _pipeline_stage(task["status"], pub_status)
                all_units.append({
                    "model": model, "experiment": exp, "member": member,
                    "variable": var, "variable_short": var, "variable_cmip7": None,
                    "variable_description": None, "variable_notes": None,
                    "pipeline_stage": stage,
                    "cmorisation_status": task["status"],
                    "publication_status": pub_status,
                    "_orphan": True,
                })

    # Build model/experiment/member index for quick nav
    index: dict[str, dict] = {}
    for plan_model, plan in plans.items():
        index[plan_model] = {"experiments": {}}
        for exp_def in plan.get("experiments", []):
            eid = exp_def["id"]
            index[plan_model]["experiments"][eid] = {
                "members": [m["variant_label"] for m in exp_def.get("members", [])],
                "priority": exp_def.get("priority", "medium"),
                "deck": exp_def.get("deck", False),
                "label": exp_def.get("label", eid),
                "theme": exp_def.get("theme", "deck" if exp_def.get("deck", False) else "default"),
                "category": exp_def.get("category"),
                "tags": exp_def.get("tags", []),
            }

    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "models": sorted(plans.keys()),
        "index": index,
        "summaries": summaries,
        "units": all_units,
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(
        f"Progress compiled: {len(all_units)} units across "
        f"{len(summaries)} (model, experiment, member) combinations → {output}"
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
