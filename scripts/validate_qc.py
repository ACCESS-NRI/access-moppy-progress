#!/usr/bin/env python3
"""Validate all progress/**/qc.json files against schemas/qc.schema.json.

Gate results are hand-editable until ACCESS-MOPPy stamps them itself, so a
typo here would otherwise show up as a silently grey gate in the dashboard
rather than as an error.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import jsonschema

ROOT = Path(__file__).parent.parent


def main() -> None:
    schema_path = ROOT / "schemas" / "qc.schema.json"
    with schema_path.open() as f:
        schema = json.load(f)
    validator = jsonschema.Draft7Validator(schema)

    qc_files = sorted((ROOT / "progress").rglob("qc.json"))
    if not qc_files:
        print("No qc.json files found — skipping.")
        return

    errors = 0
    for qc_file in qc_files:
        rel = qc_file.relative_to(ROOT)
        try:
            with qc_file.open() as f:
                record = json.load(f)
        except json.JSONDecodeError as exc:
            print(f"  {rel}: not valid JSON — {exc}")
            errors += 1
            continue

        for err in sorted(validator.iter_errors(record), key=lambda e: e.path):
            path = ".".join(str(p) for p in err.absolute_path) or "(root)"
            print(f"  {rel} .{path}: {err.message}")
            errors += 1

        # The path is the source of truth for which submission a record belongs
        # to; a record claiming to be another one is a copy-paste slip.
        model, experiment, member, _ = qc_file.relative_to(ROOT / "progress").parts
        for field, expected in (
            ("model", model),
            ("experiment_id", experiment),
            ("variant_label", member),
        ):
            actual = record.get(field)
            if actual is not None and actual != expected:
                print(f"  {rel} .{field}: {actual!r} does not match its path ({expected!r})")
                errors += 1

    if errors:
        print(f"\n{errors} error(s) in QC gate records.")
        sys.exit(1)
    print(f"All {len(qc_files)} QC gate record(s) valid.")


if __name__ == "__main__":
    main()
