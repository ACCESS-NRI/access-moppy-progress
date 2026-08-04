#!/usr/bin/env python3
"""
manage_submission.py
====================

Manage CMORisation submission records in progress/ with three actions:

- ingest: create a new cmorisation.json from a MOPPy report
- update: overwrite an existing cmorisation.json from a MOPPy report
- delete: remove an existing submission record

Examples
--------
ingest/update:
    python scripts/manage_submission.py \
        --action ingest \
        --report /path/to/moppy_batch_report.json \
        --model ACCESS-ESM1.6 \
        --member r1i1p1f1

delete entire member record:
    python scripts/manage_submission.py \
        --action delete \
        --model ACCESS-ESM1.6 \
        --experiment historical \
        --member r1i1p1f1

delete only cmorisation report file:
    python scripts/manage_submission.py \
        --action delete \
        --delete-scope cmorisation \
        --model ACCESS-ESM1.6 \
        --experiment historical \
        --member r1i1p1f1
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from ingest_report import ROOT, ingest


def _validate_member(member: str) -> None:
    if not re.match(r"^r\d+i\d+p\d+f\d+$", member):
        raise ValueError(f"Invalid variant_label: {member!r} (expected e.g. r1i1p1f1)")


def _target_paths(model: str, experiment: str, member: str) -> tuple[Path, Path]:
    member_dir = ROOT / "progress" / model / experiment / member
    cmor_path = member_dir / "cmorisation.json"
    return member_dir, cmor_path


def _prune_empty_dirs(start_dir: Path, stop_dir: Path) -> None:
    cur = start_dir
    while cur != stop_dir and cur.exists():
        if any(cur.iterdir()):
            return
        cur.rmdir()
        cur = cur.parent


def action_ingest(report: Path, model: str, member: str, experiment: str | None) -> Path:
    return ingest(
        report_path=report,
        model=model,
        member=member,
        experiment=experiment,
        force=False,
    )


def action_update(report: Path, model: str, member: str, experiment: str | None) -> Path:
    if not experiment:
        raise ValueError("--experiment is required for update")

    _, cmor_path = _target_paths(model, experiment, member)
    if not cmor_path.exists():
        raise FileNotFoundError(
            f"Cannot update missing submission: {cmor_path.relative_to(ROOT)}"
        )

    return ingest(
        report_path=report,
        model=model,
        member=member,
        experiment=experiment,
        force=True,
    )


def action_delete(model: str, experiment: str, member: str, delete_scope: str) -> None:
    member_dir, cmor_path = _target_paths(model, experiment, member)

    if delete_scope == "cmorisation":
        if not cmor_path.exists():
            raise FileNotFoundError(f"No cmorisation record found at {cmor_path.relative_to(ROOT)}")
        cmor_path.unlink()
        _prune_empty_dirs(member_dir, ROOT / "progress")
        print(f"Deleted: {cmor_path.relative_to(ROOT)}")
        return

    if not member_dir.exists():
        raise FileNotFoundError(f"No submission directory found at {member_dir.relative_to(ROOT)}")
    shutil.rmtree(member_dir)
    _prune_empty_dirs(member_dir.parent, ROOT / "progress")
    print(f"Deleted: {member_dir.relative_to(ROOT)}/")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage progress submission entries (ingest, update, delete)"
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=["ingest", "update", "delete"],
        help="Operation to perform",
    )
    parser.add_argument("--report", type=Path, help="Path to moppy_batch_report.json")
    parser.add_argument("--model", required=True, help="Model id, e.g. ACCESS-ESM1.6")
    parser.add_argument("--member", required=True, help="Variant label, e.g. r1i1p1f1")
    parser.add_argument("--experiment", help="Experiment id, e.g. historical")
    parser.add_argument(
        "--delete-scope",
        default="member",
        choices=["member", "cmorisation"],
        help="For delete action: remove entire member directory or only cmorisation.json",
    )
    args = parser.parse_args()

    try:
        _validate_member(args.member)

        if args.action in {"ingest", "update"}:
            if not args.report:
                raise ValueError("--report is required for ingest or update")
            if not args.report.exists():
                raise FileNotFoundError(f"Report file not found: {args.report}")

        if args.action == "ingest":
            action_ingest(args.report, args.model, args.member, args.experiment)
        elif args.action == "update":
            action_update(args.report, args.model, args.member, args.experiment)
        else:
            if not args.experiment:
                raise ValueError("--experiment is required for delete")
            action_delete(args.model, args.experiment, args.member, args.delete_scope)

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
