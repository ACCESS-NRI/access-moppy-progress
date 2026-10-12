#!/usr/bin/env python3
"""
sync_publications.py
====================

Tracks variables in the NCI staging and publication trees.

NCI moves output from ``admin/incoming/`` to ``staging/`` before it reaches
``publications/``. A variable in staging is not yet published. Each listing
contains one MIP-DRS7 version directory per line, holding at least one
``.nc`` file. Any dated staging prefix is removed::

    MIP-DRS7/CMIP7/CMIP/.../v20261001

Each line follows the MIP-DRS7 layout::

    MIP-DRS7/CMIP7/<activity>/<institution>/<source_id>/<experiment_id>/
        <variant_label>/<region>/<frequency>/<variable>/<branding>/<grid>/<version>

The path carries no realm, so each variable is matched back to its branded
name (``realm.variable.branding.frequency.region``) through the plans and the
ingested CMORisation reports.

Every ``publication.json`` this script writes is marked
``updated_by: sync_publications.py`` and is rewritten from the listing alone,
so a variable withdrawn from the publication tree drops out again. Records
written by hand are left untouched.

Usage
-----
    python scripts/sync_publications.py --listing published.txt --staging-listing staging.txt
    python scripts/sync_publications.py --listing published.txt --staging-listing staging.txt --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from sync_reports import MEMBER_RE, canonical_key, load_plan_vocabulary

ROOT = Path(__file__).parent.parent
PROGRESS = ROOT / "progress"
WRITER = "sync_publications.py"
DRS_DEPTH = 13

Identity = tuple[str, str, str]


def realmless(branded: str) -> str | None:
    """``atmos.tas.tavg-h2m-hxy-u.mon.glb`` -> ``tas.tavg-h2m-hxy-u.mon.glb``."""
    parts = branded.split(".")
    return ".".join(parts[1:]) if len(parts) == 5 else None


def branded_index() -> dict[str, set[str]]:
    """Map each realm-less name to the branded names it could stand for."""
    names: set[str] = set()
    for path in sorted((ROOT / "plans").glob("*.yaml")):
        with path.open() as fh:
            plan = yaml.safe_load(fh) or {}
        for exp in plan.get("experiments", []) or []:
            targets = exp.get("target_variables")
            if isinstance(targets, list):
                names.update(
                    item["cmip7_name"]
                    for item in targets
                    if isinstance(item, dict) and item.get("cmip7_name")
                )
    for path in sorted(PROGRESS.glob("*/*/*/cmorisation.json")):
        with path.open() as fh:
            names.update(task["variable"] for task in json.load(fh).get("tasks", []))

    index: dict[str, set[str]] = {}
    for name in names:
        key = realmless(name)
        if key:
            index.setdefault(key, set()).add(name)
    return index


def parse_listing(listing: Path) -> dict[Identity, dict[str, str]]:
    """Map (model, experiment, member) to {branded variable: latest version}."""
    models, experiments = load_plan_vocabulary()
    index = branded_index()
    published: dict[Identity, dict[str, str]] = {}

    for line in listing.read_text().splitlines():
        parts = line.strip().strip("/").split("/")
        # Login banners and module messages share stdout with the listing.
        if not parts or parts[0] != "MIP-DRS7":
            continue
        if len(parts) != DRS_DEPTH:
            print(f"SKIP {line}: not a MIP-DRS7 version directory", file=sys.stderr)
            continue

        source_id, experiment_id, member = parts[4:7]
        region, frequency, variable, branding = parts[7:11]
        version = parts[12]
        if not MEMBER_RE.match(member):
            print(f"SKIP {line}: invalid variant_label {member!r}", file=sys.stderr)
            continue

        candidates = index.get(f"{variable}.{branding}.{frequency}.{region}", set())
        if len(candidates) != 1:
            reason = "no planned or reported variable" if not candidates else (
                f"ambiguous between {', '.join(sorted(candidates))}"
            )
            print(f"SKIP {line}: {reason}", file=sys.stderr)
            continue

        identity = (
            models.get(canonical_key(source_id), source_id),
            experiments.get(canonical_key(experiment_id), experiment_id),
            member,
        )
        variables = published.setdefault(identity, {})
        branded = next(iter(candidates))
        variables[branded] = max(variables.get(branded, ""), version)

    return published


def build_record(identity: Identity, variables: dict[str, dict[str, str]]) -> dict:
    model, experiment, member = identity
    return {
        "model": model,
        "experiment_id": experiment,
        "variant_label": member,
        "updated_by": WRITER,
        "variables": {name: info for name, info in sorted(variables.items())},
    }


def substantive(record: dict) -> dict:
    """The record minus provenance fields that change on every write."""
    return {key: value for key, value in record.items() if key != "updated_at"}


def owned_records() -> dict[Identity, Path]:
    """publication.json files this script wrote, by identity."""
    owned: dict[Identity, Path] = {}
    for path in sorted(PROGRESS.glob("*/*/*/publication.json")):
        try:
            with path.open() as fh:
                if json.load(fh).get("updated_by") != WRITER:
                    continue
        except (OSError, json.JSONDecodeError):
            continue
        owned[tuple(path.parent.relative_to(PROGRESS).parts)] = path
    return owned


def sync(
    published: dict[Identity, dict[str, str]],
    dry_run: bool,
    staging: dict[Identity, dict[str, str]] | None = None,
) -> dict[str, int]:
    counts = {"created": 0, "updated": 0, "unchanged": 0, "removed": 0, "manual": 0}
    owned = owned_records()
    observed: dict[Identity, dict[str, dict[str, str]]] = {}
    for identity, variables in (staging or {}).items():
        observed[identity] = {
            name: {"status": "staging", "notes": f"{version} in /g/data/im55/admin/staging"}
            for name, version in variables.items()
        }
    for identity, variables in published.items():
        current = observed.setdefault(identity, {})
        current.update({
            name: {"status": "published", "notes": f"{version} in /g/data/im55/publications"}
            for name, version in variables.items()
        })

    for identity, variables in sorted(observed.items()):
        dest = PROGRESS.joinpath(*identity, "publication.json")
        record = build_record(identity, variables)
        label = "/".join(identity)

        if dest.exists():
            if identity not in owned:
                print(f"KEEP {label}: publication.json was written by hand", file=sys.stderr)
                counts["manual"] += 1
                continue
            with dest.open() as fh:
                if substantive(json.load(fh)) == substantive(record):
                    counts["unchanged"] += 1
                    continue
            outcome = "updated"
        else:
            outcome = "created"

        record["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"{outcome:9s} {label}/publication.json  ({len(variables)} staged or published)")
        counts[outcome] += 1

    for identity, path in sorted(owned.items()):
        if identity in observed:
            continue
        if not dry_run:
            path.unlink()
        print(f"removed   {'/'.join(identity)}/publication.json  (nothing staged or published)")
        counts["removed"] += 1

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Track variables in the NCI staging and publication trees"
    )
    parser.add_argument(
        "--listing",
        required=True,
        type=Path,
        help="File of published version directories, one per line",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything",
    )
    parser.add_argument(
        "--staging-listing",
        type=Path,
        help="File of staged version directories, one per line",
    )
    args = parser.parse_args()

    if not args.listing.is_file():
        print(f"ERROR: listing is not a file: {args.listing}", file=sys.stderr)
        sys.exit(1)
    if args.staging_listing is not None and not args.staging_listing.is_file():
        print(f"ERROR: staging listing is not a file: {args.staging_listing}", file=sys.stderr)
        sys.exit(1)

    published = parse_listing(args.listing)
    staging = parse_listing(args.staging_listing) if args.staging_listing else {}
    counts = sync(published, args.dry_run, staging)
    print(
        f"\n{sum(len(v) for v in staging.values())} staged and "
        f"{sum(len(v) for v in published.values())} published variable(s): "
        f"{counts['created']} created, "
        f"{counts['updated']} updated, {counts['unchanged']} unchanged, "
        f"{counts['removed']} removed, {counts['manual']} left as hand-written."
    )


if __name__ == "__main__":
    main()
