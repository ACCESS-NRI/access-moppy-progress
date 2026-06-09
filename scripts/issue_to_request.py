#!/usr/bin/env python3
"""
issue_to_request.py
===================

Parse a GitHub Issue body (submitted via the propose_submission.yml form)
and emit a requests/<model>_<experiment_id>_<variant_label>.yaml file.

Usage (CI)
----------
    python scripts/issue_to_request.py \
        --body   /tmp/issue_body.txt \
        --number 42 \
        --output requests/

Usage (local test)
------------------
    gh issue view 42 --json body -q .body | \
        python scripts/issue_to_request.py --number 42 --output requests/

Exit codes
----------
    0 — request YAML written successfully
    1 — required fields missing; message printed to stderr
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_form_body(text: str) -> dict[str, str]:
    """
    Parse the structured body produced by a GitHub issue form.

    GitHub renders each form field as:
        ### Field Label\n\nField value\n\n
    or
        ### Field Label\n\n_No response_\n\n

    Returns a dict mapping normalised label → value string.
    """
    result: dict[str, str] = {}
    parts = re.split(r"^###\s+", text, flags=re.MULTILINE)
    for part in parts:
        if not part.strip():
            continue
        lines = part.split("\n", 1)
        label = lines[0].strip().rstrip("*").strip()
        value = lines[1].strip() if len(lines) > 1 else ""
        if value.lower() in ("_no response_", "none", "n/a", ""):
            value = ""
        result[label] = value
    return result


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9\-]", "-", value.lower()).strip("-")


# ── YAML writer ───────────────────────────────────────────────────────────────

def _scalar(value: str) -> str:
    """Quote a scalar value if needed."""
    if not value:
        return '""'
    if any(c in value for c in (':', '{', '}', '[', ']', '#', '&', '*',
                                 '!', '|', '>', "'", '"', '%', '@', '`', ',')):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _literal_block(text: str, indent: int = 2) -> str:
    """Render a multi-line string as a YAML literal block scalar."""
    prefix = " " * indent
    lines = text.splitlines()
    body = "\n".join(f"{prefix}  {line}" for line in lines)
    return f"|\n{body}"


def build_yaml(fields: dict[str, str], issue_number: int) -> tuple[str, str]:
    """
    Build the YAML content and the output filename stem from parsed form fields.

    Returns (filename_stem, yaml_content).
    Raises ValueError if required fields are absent.
    """
    # ── required ──────────────────────────────────────────────────────────
    missing = []
    for req in ("Model", "Experiment id", "Variant label",
                "NCI project code", "Input folder (raw model output)"):
        if not fields.get(req):
            missing.append(req)
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    model         = fields["Model"].replace("Other (describe in Notes)", "unknown")
    mip_era       = (fields.get("MIP era") or "CMIP7").strip()
    experiment_id = fields["Experiment id"].strip()
    variant_label = fields["Variant label"].strip()
    source_id     = (fields.get("CMIP source_id") or "").strip()
    activity_raw  = (fields.get("Activity id") or "cmip").strip().lower()
    activity_id   = activity_raw if activity_raw not in ("other", "") else "cmip"

    gadi_project  = fields.get("NCI project code", "").strip()
    input_folder  = fields.get("Input folder (raw model output)", "").strip()
    output_folder = (fields.get("Output folder (CMORised files)") or "").strip()
    storage       = (fields.get("PBS storage flags") or "").strip()
    worker_init   = (fields.get("Worker init commands") or "").strip()

    run_start     = (fields.get("Run start date") or "").strip()
    run_end       = (fields.get("Run end date") or "").strip()

    parent_exp     = (fields.get("Parent experiment id") or "").strip()
    parent_variant = (fields.get("Parent variant label") or "").strip()
    branch_year    = (fields.get("Branch year") or "").strip()

    target_choice = fields.get("Target variables", "All")
    variable_list = (fields.get("Variable list (if Subset above)") or "").strip()
    file_patterns = (fields.get("Custom file patterns (optional)") or "").strip()

    pbs_queue    = (fields.get("PBS queue") or "normal").strip()
    pbs_mem      = (fields.get("Default memory per job") or "32GB").strip()
    pbs_walltime = (fields.get("Default walltime per job") or "02:00:00").strip()
    priority     = (fields.get("Priority") or "medium").strip().lower()
    notes        = (fields.get("Notes") or "").strip()

    filename_stem = f"{_slug(model)}_{_slug(experiment_id)}_{_slug(variant_label)}"

    # ── build lines ───────────────────────────────────────────────────────
    lines: list[str] = []

    def L(line: str = "") -> None:
        lines.append(line)

    L(f"# Submission request: {model} / {experiment_id} / {variant_label}")
    L(f"# Generated automatically from GitHub issue #{issue_number}.")
    L("# Review and adjust before merging — especially cmip_metadata and dates.")
    L("# Conforms to schemas/submission_request.schema.json")
    L()
    L(f"model: {_scalar(model)}")
    if source_id:
        L(f"source_id: {_scalar(source_id)}")
    else:
        L("# source_id: CHANGEME")
    L(f"experiment_id: {_scalar(experiment_id)}")
    L(f"variant_label: {_scalar(variant_label)}")
    L("grid_label: gn")
    L(f"activity_id: {_scalar(activity_id)}")
    L(f"mip_era: {mip_era}")
    L()
    L("status: needs-review")
    L(f"priority: {priority}")
    L(f"issue: {issue_number}")
    L()
    L("gadi:")
    L(f"  project: {gadi_project}")
    L(f"  input_folder: {_scalar(input_folder)}")
    if output_folder:
        L(f"  output_folder: {_scalar(output_folder)}")
    if storage:
        L(f"  storage: {_scalar(storage)}")
    if worker_init:
        L(f"  worker_init: {_literal_block(worker_init, indent=2)}")
    L()
    L("pbs:")
    L(f"  queue: {pbs_queue}")
    L("  cpus_per_node: 14")
    L(f"  mem: {pbs_mem}")
    L("  jobfs: 100GB")
    L(f"  walltime: {_scalar(pbs_walltime)}")

    if parent_exp:
        L()
        L("cmip_metadata:")
        L(f"  parent_experiment_id: {_scalar(parent_exp)}")
        L(f"  parent_source_id: {_scalar(source_id) if source_id else 'CHANGEME'}")
        L(f"  parent_variant_label: {_scalar(parent_variant or variant_label)}")
        L("  parent_activity_id: cmip")
        L(f"  parent_mip_era: {mip_era}")
        L(f"  branch_year: {branch_year if branch_year else 'CHANGEME'}")
        L("  branch_method: standard")

    if run_start or run_end:
        L()
        L("run_dates:")
        L(f"  start: {_scalar(run_start) if run_start else 'CHANGEME'}")
        L(f"  end:   {_scalar(run_end) if run_end else 'CHANGEME'}")

    L()
    L("target_variables:")
    if "subset" in target_choice.lower() and variable_list:
        for var in variable_list.splitlines():
            if var.strip():
                L(f"  - {var.strip()}")
    else:
        L('  - "*"  # all variables from submission plan')

    if file_patterns:
        L()
        L("file_patterns:")
        for pat in file_patterns.splitlines():
            if pat.strip():
                L(f"  {pat.strip()}")

    L()
    L("notes: >")
    if notes:
        for note_line in notes.splitlines():
            L(f"  {note_line}")
    L(f"  Proposed via GitHub issue #{issue_number}.")

    return filename_stem, "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--body", default="-",
        help="Path to file containing the issue body, or '-' to read from stdin",
    )
    parser.add_argument(
        "--number", type=int, required=True,
        help="GitHub issue number (embedded in the generated YAML)",
    )
    parser.add_argument(
        "--output", default="requests",
        help="Directory to write the request YAML (default: requests/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the YAML to stdout instead of writing a file",
    )
    args = parser.parse_args(argv)

    if args.body == "-":
        body_text = sys.stdin.read()
    else:
        body_text = Path(args.body).read_text()

    fields = _parse_form_body(body_text)

    try:
        stem, content = build_yaml(fields, args.number)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(content)
        return 0

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}.yaml"
    out_path.write_text(content)
    print(f"Written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
