#!/usr/bin/env python3
"""Validate all plans/*.yaml files against schemas/plan.schema.json."""
from __future__ import annotations
import json, sys
from pathlib import Path
import yaml, jsonschema

ROOT = Path(__file__).parent.parent

def main() -> None:
    schema_path = ROOT / "schemas" / "plan.schema.json"
    with schema_path.open() as f:
        schema = json.load(f)
    validator = jsonschema.Draft7Validator(schema)
    errors = 0
    for plan_file in sorted((ROOT / "plans").glob("*.yaml")):
        with plan_file.open() as f:
            plan = yaml.safe_load(f)
        errs = sorted(validator.iter_errors(plan), key=lambda e: e.path)
        for err in errs:
            path = ".".join(str(p) for p in err.absolute_path) or "(root)"
            print(f"  {plan_file.name} .{path}: {err.message}")
            errors += 1
    if errors:
        print(f"\n{errors} error(s) in plan files.")
        sys.exit(1)
    print(f"All {len(list((ROOT / 'plans').glob('*.yaml')))} plan file(s) valid.")

if __name__ == "__main__":
    main()
