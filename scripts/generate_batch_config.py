#!/usr/bin/env python3
"""
generate_batch_config.py
========================

Generates a ready-to-run ACCESS-MOPPy batch config YAML from an accepted
submission request in requests/.

Usage
-----
    python scripts/generate_batch_config.py \\
        --request requests/<model>_<experiment>_<member>.yaml \\
        --output  /path/to/batch_config.yml

The output file can be passed directly to MOPPy:
    moppy-batch run /path/to/batch_config.yml

If --output is omitted the config is printed to stdout so it can be piped
or inspected before writing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent


def _resolve_variables(req: dict) -> list[str]:
    tv = req.get("target_variables", "*")
    if tv == "*":
        # Fall back to the matching plan entry if available
        model = req["model"]
        exp   = req["experiment_id"]
        plan_file = ROOT / "plans" / f"{model}.yaml"
        if plan_file.exists():
            with plan_file.open() as fh:
                plan = yaml.safe_load(fh)
            for exp_def in plan.get("experiments", []):
                if exp_def["id"] == exp:
                    tv = exp_def.get("target_variables", "*")
                    if tv != "*":
                        return list(tv)
        # If plan also uses *, return a placeholder comment
        return ["# Add variable list here, e.g. Amon.tas"]
    return list(tv)


def generate(req: dict) -> dict:
    """Build the MOPPy batch config dict from a submission request."""
    gadi = req.get("gadi", {})
    pbs  = req.get("pbs",  {})
    meta = req.get("cmip_metadata", {})
    dates = req.get("run_dates", {})

    variables = _resolve_variables(req)

    config: dict = {
        "experiment_id": req["experiment_id"],
        "source_id":     req["source_id"],
        "variant_label": req["variant_label"],
        "grid_label":    req.get("grid_label", "gn"),
        "activity_id":   req.get("activity_id", "CMIP"),

        "input_folder":  gadi.get("input_folder", ""),
        "output_folder": gadi.get("output_folder", ""),

        "variables": variables,

        "queue":         pbs.get("queue",         "normal"),
        "cpus_per_node": pbs.get("cpus_per_node", 14),
        "mem":           pbs.get("mem",           "32GB"),
        "jobfs":         pbs.get("jobfs",         "100GB"),
        "walltime":      pbs.get("walltime",      "02:00:00"),

        "scheduler_options": f"#PBS -P {gadi.get('project', 'CHANGEME')}",
        "storage":           gadi.get("storage", ""),
    }

    if gadi.get("worker_init"):
        config["worker_init"] = gadi["worker_init"]

    if gadi.get("file_patterns"):
        config["file_patterns"] = gadi["file_patterns"]

    # Optional CMIP branching metadata (written as comments if not set)
    if meta:
        cmip_block = {}
        for key in ["parent_experiment_id", "parent_source_id", "parent_variant_label",
                    "parent_activity_id", "branch_year", "branch_method"]:
            if meta.get(key) is not None:
                cmip_block[key] = meta[key]
        if cmip_block:
            config["cmip_parent"] = cmip_block

    if dates:
        config["run_dates"] = {k: v for k, v in dates.items() if v}

    # Remove None-valued sentinel comment keys before serialising
    config = {k: v for k, v in config.items() if v is not None}

    return config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a MOPPy batch config YAML from a submission request"
    )
    parser.add_argument(
        "--request", required=True, type=Path,
        help="Path to the submission request YAML (requests/*.yaml)"
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output path for the batch config YAML. Defaults to stdout."
    )
    args = parser.parse_args()

    if not args.request.exists():
        print(f"ERROR: request file not found: {args.request}", file=sys.stderr)
        sys.exit(1)

    with args.request.open() as fh:
        req = yaml.safe_load(fh)

    config = generate(req)
    text = (
        "# ACCESS-MOPPy batch configuration\n"
        f"# Source: {args.request.name}\n"
        f"# Run: moppy-batch run <this_file>\n\n"
    ) + yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Batch config written to {args.output}")
        print(f"Run with: moppy-batch run {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
