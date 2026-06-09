#!/usr/bin/env python3
"""
ingest_report.py
================

Places a moppy_batch_report.json produced by ACCESS-MOPPy into the correct
location in the progress/ hierarchy of this registry, adding provenance fields.

Usage
-----
    python scripts/ingest_report.py \\
        --report /path/to/moppy_batch_report.json \\
        --model  ACCESS-ESM1.6 \\
        --member r1i1p1f1

The experiment id is read from the report itself (field ``experiment_id``).
You may override it with ``--experiment`` if it is absent from the report.

After ingestion, commit and push the new file:
    git add progress/...
    git commit -m "chore: ingest historical/r1i1p1f1 cmorisation report"
    git push
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent


def ingest(
    report_path: Path,
    model: str,
    member: str,
    experiment: str | None = None,
    force: bool = False,
) -> Path:
    with report_path.open() as fh:
        report = json.load(fh)

    # Resolve experiment id
    exp_id = experiment or report.get("experiment_id")
    if not exp_id:
        raise ValueError(
            "Could not determine experiment_id from report. "
            "Pass --experiment explicitly."
        )

    # Validate member label
    import re
    if not re.match(r"^r\d+i\d+p\d+f\d+$", member):
        raise ValueError(f"Invalid variant_label: {member!r} (expected e.g. r1i1p1f1)")

    # Add provenance fields
    report["model"] = model
    report["variant_label"] = member
    report["ingested_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if "experiment_id" not in report:
        report["experiment_id"] = exp_id

    # Target path
    dest = ROOT / "progress" / model / exp_id / member / "cmorisation.json"

    if dest.exists() and not force:
        print(
            f"WARNING: {dest.relative_to(ROOT)} already exists. "
            "Use --force to overwrite.",
            file=sys.stderr,
        )
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    tasks = report.get("tasks", [])
    summary = report.get("summary", {})
    print(
        f"Ingested: {model}/{exp_id}/{member}/cmorisation.json\n"
        f"  Status   : {report.get('status')}\n"
        f"  Tasks    : {summary.get('total', len(tasks))} total, "
        f"{summary.get('completed', 0)} completed, "
        f"{summary.get('failed', 0)} failed"
    )
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a moppy_batch_report.json into the progress registry"
    )
    parser.add_argument("--report", required=True, type=Path, help="Path to moppy_batch_report.json")
    parser.add_argument("--model",  required=True, help="Model id, e.g. ACCESS-ESM1.6")
    parser.add_argument("--member", required=True, help="Variant label, e.g. r1i1p1f1")
    parser.add_argument("--experiment", help="Experiment id (overrides value in report)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing file")
    args = parser.parse_args()

    try:
        ingest(
            report_path=args.report,
            model=args.model,
            member=args.member,
            experiment=args.experiment,
            force=args.force,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
