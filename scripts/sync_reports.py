#!/usr/bin/env python3
"""
sync_reports.py
===============

Bulk-ingests a tree of MOPPy batch reports rsynced from Gadi into the
``progress/`` hierarchy of this registry.

The expected source tree is what this rsync produces::

    rsync -av --prune-empty-dirs \\
        --include='*/' \\
        --include='batch_config.yml' \\
        --include='moppy_batch_report_*.json' \\
        --exclude='*' \\
        rb5533@gadi.nci.org.au:/scratch/p73/ESM1p6_CMORised/ ./ESM1p6_CMORised/

Each run directory may hold several ``moppy_batch_report_<timestamp>.json``
files; only the most recent one per (model, experiment, member) is ingested.
Identifiers come from the report itself, falling back to the sibling
``batch_config.yml`` for older reports that omit them, and are normalised
against ``plans/*.yaml`` so that e.g. ``ACCESS-ESM1-6``/``esm-picontrol``
land in ``progress/ACCESS-ESM1.6/esm-piControl/``.

Writes are idempotent: a destination file is only rewritten when the report
content actually changed, so re-running produces no spurious diffs.

Usage
-----
    python scripts/sync_reports.py --source ESM1p6_CMORised
    python scripts/sync_reports.py --source ESM1p6_CMORised --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from qc_from_report import write_qc_record

ROOT = Path(__file__).parent.parent

REPORT_GLOB = "moppy_batch_report_*.json"
CONFIG_NAME = "batch_config.yml"
MEMBER_RE = re.compile(r"^r\d+i\d+p\d+f\d+$")
FILENAME_TS_RE = re.compile(r"moppy_batch_report_(\d{8}T\d{6}Z)\.json$")


def canonical_key(value: str) -> str:
    """Fold a model/experiment id for case- and punctuation-insensitive matching."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def load_plan_vocabulary() -> tuple[dict[str, str], dict[str, str]]:
    """Return ({folded model: canonical model}, {folded experiment: canonical}) from plans/."""
    models: dict[str, str] = {}
    experiments: dict[str, str] = {}
    for path in sorted((ROOT / "plans").glob("*.yaml")):
        with path.open() as fh:
            plan = yaml.safe_load(fh) or {}
        model = plan.get("model")
        if model:
            models[canonical_key(model)] = model
        for exp in plan.get("experiments", []) or []:
            exp_id = exp.get("id")
            if exp_id:
                experiments[canonical_key(exp_id)] = exp_id
    return models, experiments


def report_timestamp(path: Path, report: dict) -> str:
    """Sort key for picking the most recent report; created_at, else filename stamp."""
    created = report.get("created_at")
    if created:
        return created
    match = FILENAME_TS_RE.search(path.name)
    return match.group(1) if match else ""


def run_directory(path: Path, source: Path) -> Path:
    """The run directory owning ``path``: nearest ancestor holding a batch_config.yml.

    A run directory often keeps superseded reports in a subdirectory of its own
    (``<run>/archives/``). Those are the same run, so they must resolve to the
    same directory as the live report beside ``batch_config.yml`` -- otherwise
    an archived report looks like a second run laying claim to the identity, and
    the collision check below drops the combination, newest report included.
    """
    for directory in (path.parent, *path.parent.parents):
        if (directory / CONFIG_NAME).exists():
            return directory
        if directory == source:
            break
    return path.parent


def read_batch_config(directory: Path) -> dict:
    """Identifier fields from the sibling batch_config.yml, or {} if unavailable."""
    config_path = directory / CONFIG_NAME
    if not config_path.exists():
        return {}
    try:
        with config_path.open() as fh:
            return yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        print(f"WARNING: could not parse {config_path}: {exc}", file=sys.stderr)
        return {}


def resolve_identity(
    path: Path,
    report: dict,
    models: dict[str, str],
    experiments: dict[str, str],
    run_dir: Path | None = None,
) -> tuple[str, str, str] | None:
    """Resolve (model, experiment, member) for one report, or None if incomplete."""
    fields = ("source_id", "experiment_id", "variant_label")

    # Take the identity as a unit rather than field by field: a stale report left
    # behind in a re-purposed run directory can carry the *previous* experiment_id
    # alongside null source_id/variant_label, and blending the two sources would
    # invent a combination that never ran.
    resolved = {field: report.get(field) for field in fields}
    if not all(resolved.values()):
        config = read_batch_config(run_dir if run_dir is not None else path.parent)
        resolved = {field: config.get(field) for field in fields}

    missing = [field for field, value in resolved.items() if not value]
    if missing:
        print(
            f"SKIP {path}: missing {', '.join(missing)} in report and {CONFIG_NAME}",
            file=sys.stderr,
        )
        return None

    member = str(resolved["variant_label"])
    if not MEMBER_RE.match(member):
        print(f"SKIP {path}: invalid variant_label {member!r}", file=sys.stderr)
        return None

    source_id = str(resolved["source_id"])
    experiment_id = str(resolved["experiment_id"])
    model = models.get(canonical_key(source_id), source_id)
    experiment = experiments.get(canonical_key(experiment_id), experiment_id)

    if canonical_key(source_id) not in models:
        print(f"WARNING: {path}: no plan for model {source_id!r}; using it verbatim", file=sys.stderr)
    if canonical_key(experiment_id) not in experiments:
        print(
            f"WARNING: {path}: experiment {experiment_id!r} not in any plan; using it verbatim",
            file=sys.stderr,
        )

    return model, experiment, member


def collect_latest(
    source: Path, allow_collisions: bool = False
) -> dict[tuple[str, str, str], tuple[Path, dict]]:
    """Map (model, experiment, member) to the most recent report found under source.

    Reruns of the same job land several reports in one run directory -- at its
    top level or archived in a subdirectory of it -- and the newest wins. Two *different* run directories claiming the same identity is
    ambiguous: it may be a legitimate rerun under a new directory, or a
    copy-pasted experiment_id in batch_config.yml pointing a run at the wrong
    record. Such keys are reported and skipped, so an unattended run never
    silently overwrites one experiment's record with another's; pass
    allow_collisions to take the most recent report instead.
    """
    models, experiments = load_plan_vocabulary()
    latest: dict[tuple[str, str, str], tuple[str, Path, dict]] = {}
    run_dirs: dict[tuple[str, str, str], set[Path]] = {}

    for path in sorted(source.rglob(REPORT_GLOB)):
        try:
            with path.open() as fh:
                report = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"SKIP {path}: unreadable ({exc})", file=sys.stderr)
            continue

        run_dir = run_directory(path, source)
        identity = resolve_identity(path, report, models, experiments, run_dir)
        if identity is None:
            continue

        run_dirs.setdefault(identity, set()).add(run_dir)
        stamp = report_timestamp(path, report)
        current = latest.get(identity)
        if current is None or stamp > current[0]:
            latest[identity] = (stamp, path, report)

    for identity, dirs in sorted(run_dirs.items()):
        if len(dirs) > 1:
            model, experiment, member = identity
            listed = ", ".join(str(d) for d in sorted(dirs))
            action = "COLLISION (using most recent)" if allow_collisions else "SKIP"
            print(
                f"{action} {model}/{experiment}/{member}: claimed by {len(dirs)} run "
                f"directories ({listed}). Check experiment_id/variant_label in each "
                f"{CONFIG_NAME} on Gadi.",
                file=sys.stderr,
            )
            if not allow_collisions:
                del latest[identity]

    return {identity: (path, report) for identity, (_, path, report) in latest.items()}


def substantive(record: dict) -> dict:
    """The record minus provenance fields that change on every ingest."""
    return {key: value for key, value in record.items() if key != "ingested_at"}


def write_record(
    model: str,
    experiment: str,
    member: str,
    source_path: Path,
    report: dict,
    dry_run: bool,
) -> str:
    """Write one cmorisation.json. Returns 'created', 'updated' or 'unchanged'."""
    record = dict(report)
    record["model"] = model
    record["experiment_id"] = experiment
    record["variant_label"] = member

    dest = ROOT / "progress" / model / experiment / member / "cmorisation.json"

    if dest.exists():
        with dest.open() as fh:
            existing = json.load(fh)
        if substantive(existing) == substantive(record):
            return "unchanged"
        outcome = "updated"
    else:
        outcome = "created"

    record["ingested_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    print(f"{outcome:9s} {model}/{experiment}/{member}  <- {source_path}")
    return outcome


def write_gates(
    model: str,
    experiment: str,
    member: str,
    source_path: Path,
    report: dict,
    dry_run: bool,
) -> str:
    """Write the member's qc.json from the gate results in its report."""
    outcome, count = write_qc_record(
        model,
        experiment,
        member,
        report,
        source_report=source_path.name,
        checked_by="sync_reports.py",
        dry_run=dry_run,
    )
    if outcome in ("created", "updated"):
        print(f"{outcome:9s} {model}/{experiment}/{member}/qc.json  ({count} variables)")
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a rsynced tree of MOPPy batch reports into progress/"
    )
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Directory holding the rsynced Gadi tree, e.g. ESM1p6_CMORised",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything",
    )
    parser.add_argument(
        "--allow-collisions",
        action="store_true",
        help=(
            "When several run directories claim the same experiment/member, "
            "ingest the most recent instead of skipping the combination"
        ),
    )
    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"ERROR: source is not a directory: {args.source}", file=sys.stderr)
        sys.exit(1)

    latest = collect_latest(args.source, allow_collisions=args.allow_collisions)
    if not latest:
        print(f"ERROR: no usable {REPORT_GLOB} found under {args.source}", file=sys.stderr)
        sys.exit(1)

    counts = {"created": 0, "updated": 0, "unchanged": 0}
    gate_counts = {"created": 0, "updated": 0, "unchanged": 0, "absent": 0}
    for (model, experiment, member), (path, report) in sorted(latest.items()):
        outcome = write_record(model, experiment, member, path, report, args.dry_run)
        counts[outcome] += 1
        gate_counts[write_gates(model, experiment, member, path, report, args.dry_run)] += 1

    print(
        f"\n{len(latest)} report(s) considered: "
        f"{counts['created']} created, {counts['updated']} updated, "
        f"{counts['unchanged']} unchanged."
    )
    print(
        f"Release gates: {gate_counts['created']} created, "
        f"{gate_counts['updated']} updated, {gate_counts['unchanged']} unchanged, "
        f"{gate_counts['absent']} report(s) carried no gate results."
    )


if __name__ == "__main__":
    main()
