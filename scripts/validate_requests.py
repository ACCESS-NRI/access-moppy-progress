#!/usr/bin/env python3
"""Validate all requests/*.yaml files against schemas/submission_request.schema.json."""
from __future__ import annotations
import json, sys
from pathlib import Path
import yaml, jsonschema

ROOT = Path(__file__).parent.parent

def main() -> None:
    schema_path = ROOT / "schemas" / "submission_request.schema.json"
    with schema_path.open() as f:
        schema = json.load(f)
    validator = jsonschema.Draft7Validator(schema)
    errors = 0
    req_files = sorted((ROOT / "requests").glob("*.yaml"))
    if not req_files:
        print("No request files found — skipping.")
        return
    for req_file in req_files:
        with req_file.open() as f:
            req = yaml.safe_load(f)
        errs = sorted(validator.iter_errors(req), key=lambda e: e.path)
        for err in errs:
            path = ".".join(str(p) for p in err.absolute_path) or "(root)"
            print(f"  {req_file.name} .{path}: {err.message}")
            errors += 1
    if errors:
        print(f"\n{errors} error(s) in request files.")
        sys.exit(1)
    print(f"All {len(req_files)} request file(s) valid.")

if __name__ == "__main__":
    main()
