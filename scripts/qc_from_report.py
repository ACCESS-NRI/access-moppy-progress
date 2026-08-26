#!/usr/bin/env python3
"""
qc_from_report.py
=================

Extracts release gate results from a MOPPy batch report into the ``qc.json``
record the dashboard reads.

ACCESS-MOPPy stamps what its workers checked onto each task:

* ``tasks[].output_summary.gates`` — the value-range check run after each file
  is written, and the ``cmip7repack`` that ran on it.
* ``tasks[].compliance`` — the CF/WCRP compliance verdict, either from a run
  with ``compliance_check: true`` or from ``moppy-compliance-backfill``.

Older reports predate those fields. For them the batch-level ``qc`` block —
produced by ``moppy-batch-report`` when it is run without ``--skip-qc`` — is
used as a fallback for the range gate, matched back to tasks by output file
path.

Nothing is invented here: a gate a report says nothing about is simply left
out, and the dashboard shows it as ``not_run``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent

SCHEMA_VERSION = "access-moppy.qc.v1"

#: Longest single-line message carried into a gate record. The dashboard shows
#: these on hover, so a whole compliance-checker dump is unhelpful there — the
#: report_path points at the full detail.
MESSAGE_LIMIT = 240


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _one_line(text: object) -> str | None:
    """Condense a possibly multi-line checker message to one readable line."""
    if text is None:
        return None
    if isinstance(text, list):
        text = " ".join(str(part) for part in text)
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if not lines:
        return None
    message = lines[0]
    if len(lines) > 1:
        message += f" (+{len(lines) - 1} more)"
    if len(message) > MESSAGE_LIMIT:
        message = message[: MESSAGE_LIMIT - 1] + "…"
    return message


def _stamped_gates(task: dict) -> dict[str, dict]:
    """Gates the worker recorded on this task, if it was a recent enough run."""
    summary = task.get("output_summary")
    if not isinstance(summary, dict):
        return {}
    gates = summary.get("gates")
    if not isinstance(gates, dict):
        return {}

    extracted: dict[str, dict] = {}
    for name in ("range", "repack"):
        gate = gates.get(name)
        if isinstance(gate, dict) and gate.get("result") in ("pass", "warn", "fail"):
            record = {key: value for key, value in gate.items() if value is not None}
            if name == "range":
                record.setdefault("check_id", "cmip7_ranges")
                if record.get("message"):
                    record["message"] = _one_line(record["message"])
            extracted[name] = record
    return extracted


def _compliance_gate(task: dict) -> dict | None:
    """The WCRP gate from a task's recorded compliance verdict."""
    compliance = task.get("compliance")
    if not isinstance(compliance, dict) or "passed" not in compliance:
        return None

    passed = bool(compliance["passed"])
    environment_warning = bool(compliance.get("environment_warning"))

    record: dict = {"check_id": "wcrp"}
    if not passed:
        record["result"] = "fail"
    elif environment_warning:
        # The checker ran without its vocabulary database, so the CV checks
        # did not really happen. Recording that as a clean pass would claim
        # an audit that was never performed.
        record["result"] = "warn"
        record["environment_warning"] = True
    else:
        record["result"] = "pass"

    for key in ("suites", "cv_version", "report_path", "backfilled", "checked_at"):
        value = compliance.get(key)
        if value is not None:
            record[key] = value

    message = _one_line(compliance.get("failed_checks") or compliance.get("error"))
    if message:
        record["message"] = message
    elif environment_warning:
        record["message"] = (
            "Checker environment incomplete: WCRP vocabulary checks did not run."
        )
    return record


def _range_gates_from_batch_qc(report: dict, tasks: list[dict]) -> dict[str, dict]:
    """Range gates from the batch-level ``qc`` block, for older reports.

    ``moppy-batch-report`` run without ``--skip-qc`` validates every file under
    the output folder and lists the failures and warnings by file path. Tasks
    are matched on those paths, which the task's own ``output_summary`` records
    — no filename parsing required.
    """
    qc = report.get("qc")
    if not isinstance(qc, dict) or not qc.get("total"):
        return {}

    findings: dict[str, dict] = {}
    for entry in qc.get("failures", []) or []:
        if isinstance(entry, dict) and entry.get("file"):
            findings[str(entry["file"])] = {"result": "fail", "entry": entry}
    for entry in qc.get("warnings", []) or []:
        if isinstance(entry, dict) and entry.get("file"):
            findings.setdefault(
                str(entry["file"]), {"result": "warn", "entry": entry}
            )

    gates: dict[str, dict] = {}
    for task in tasks:
        variable = task.get("variable")
        summary = task.get("output_summary")
        if not variable or not isinstance(summary, dict):
            continue
        paths = [
            str(item["path"])
            for item in summary.get("files", [])
            if isinstance(item, dict) and item.get("path")
        ]
        if not paths:
            continue

        finding = next(
            (findings[path] for path in paths if path in findings),
            None,
        )
        if finding is None:
            # Every file under the output folder was validated, and none of
            # this task's files were reported — so they passed.
            gates[variable] = {"result": "pass", "check_id": "cmip7_ranges"}
            continue

        entry = finding["entry"]
        record: dict = {"result": finding["result"], "check_id": "cmip7_ranges"}
        if entry.get("observed_range"):
            record["observed"] = list(entry["observed_range"])
        if entry.get("allowed_range"):
            record["allowed"] = list(entry["allowed_range"])
        if entry.get("units"):
            record["units"] = entry["units"]
        message = _one_line(entry.get("error") or entry.get("warning"))
        if message:
            record["message"] = message
        gates[variable] = record
    return gates


def gates_from_report(report: dict) -> dict[str, dict[str, dict]]:
    """Return ``{variable: {gate: record}}`` for everything the report knows."""
    tasks = [task for task in report.get("tasks", []) if isinstance(task, dict)]
    fallback_range = _range_gates_from_batch_qc(report, tasks)

    variables: dict[str, dict[str, dict]] = {}
    for task in tasks:
        variable = task.get("variable")
        if not variable:
            continue

        gates = _stamped_gates(task)
        if "range" not in gates and variable in fallback_range:
            gates["range"] = fallback_range[variable]

        wcrp = _compliance_gate(task)
        if wcrp is not None:
            gates["wcrp"] = wcrp

        if gates:
            variables[str(variable)] = gates
    return variables


def build_qc_record(
    model: str,
    experiment: str,
    member: str,
    report: dict,
    source_report: str | None = None,
    checked_by: str | None = None,
) -> dict | None:
    """Build a qc.json record, or None when the report carries no gate results."""
    variables = gates_from_report(report)
    if not variables:
        return None

    record: dict = {
        "schema_version": SCHEMA_VERSION,
        "model": model,
        "experiment_id": experiment,
        "variant_label": member,
        "checked_at": _utc_now_iso(),
    }
    if checked_by:
        record["checked_by"] = checked_by
    if source_report:
        record["source_report"] = source_report
    record["variables"] = variables
    return record


def substantive(record: dict) -> dict:
    """The record minus fields that change on every ingest."""
    return {key: value for key, value in record.items() if key != "checked_at"}


def write_qc_record(
    model: str,
    experiment: str,
    member: str,
    report: dict,
    source_report: str | None = None,
    checked_by: str | None = None,
    dry_run: bool = False,
) -> tuple[str, int]:
    """Write ``qc.json`` beside the member's report.

    Returns ``(outcome, variable_count)`` where outcome is one of ``created``,
    ``updated``, ``unchanged`` or ``absent`` — the last meaning the report
    carried no gate results, so nothing was written.
    """
    record = build_qc_record(
        model, experiment, member, report, source_report, checked_by
    )
    if record is None:
        return "absent", 0

    dest = ROOT / "progress" / model / experiment / member / "qc.json"
    if dest.exists():
        with dest.open() as fh:
            existing = json.load(fh)
        if substantive(existing) == substantive(record):
            return "unchanged", len(record["variables"])
        outcome = "updated"
    else:
        outcome = "created"

    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    return outcome, len(record["variables"])
