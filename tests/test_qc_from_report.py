"""Tests for extracting release gates out of a MOPPy batch report.

The extraction has to be conservative: a gate the report says nothing about
must come out absent, so the dashboard shows "not run" rather than implying a
check that never happened.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from qc_from_report import build_qc_record, gates_from_report  # noqa: E402


def _task(variable, *, status="completed", gates=None, compliance=None, files=None):
    task = {"variable": variable, "status": status}
    summary = {}
    if gates is not None:
        summary["gates"] = gates
    if files is not None:
        summary["files"] = [{"path": path} for path in files]
    if summary:
        task["output_summary"] = summary
    if compliance is not None:
        task["compliance"] = compliance
    return task


# ── Gates the worker stamped ────────────────────────────────────────────────


def test_stamped_range_and_repack_gates_are_extracted():
    report = {
        "tasks": [
            _task(
                "atmos.tas.tavg-h2m-hxy-u.mon.glb",
                gates={
                    "range": {
                        "result": "warn",
                        "observed": [-2.1, 34.8],
                        "allowed": [-2.0, 34.0],
                        "units": "degC",
                        "message": "outside allowed range.",
                    },
                    "repack": {"result": "pass", "tool": "cmip7repack"},
                },
            )
        ]
    }

    gates = gates_from_report(report)["atmos.tas.tavg-h2m-hxy-u.mon.glb"]

    assert gates["range"]["result"] == "warn"
    assert gates["range"]["observed"] == [-2.1, 34.8]
    assert gates["range"]["check_id"] == "cmip7_ranges"
    assert gates["repack"] == {"result": "pass", "tool": "cmip7repack"}


def test_reports_without_gates_yield_nothing():
    """The reports ingested before MOPPy stamped its results must stay empty."""
    report = {"tasks": [_task("atmos.tas.tavg-h2m-hxy-u.mon.glb")]}

    assert gates_from_report(report) == {}


def test_a_failed_task_carries_no_gates():
    report = {"tasks": [_task("atmos.pr.tavg-u-hxy-u.3hr.glb", status="failed")]}

    assert gates_from_report(report) == {}


def test_an_unrecognised_gate_result_is_dropped():
    report = {
        "tasks": [_task("atmos.tas.tavg-h2m-hxy-u.mon.glb", gates={"range": {"result": "?"}})]
    }

    assert gates_from_report(report) == {}


# ── The WCRP gate ───────────────────────────────────────────────────────────


def test_compliance_pass_becomes_a_wcrp_gate():
    report = {
        "tasks": [
            _task(
                "atmos.tas.tavg-h2m-hxy-u.mon.glb",
                compliance={
                    "passed": True,
                    "cv_version": "esgvoc-1.4.2",
                    "suites": ["cf:1.11", "wcrp_cmip7:1.0"],
                    "backfilled": True,
                    "environment_warning": False,
                },
            )
        ]
    }

    wcrp = gates_from_report(report)["atmos.tas.tavg-h2m-hxy-u.mon.glb"]["wcrp"]

    assert wcrp["result"] == "pass"
    assert wcrp["check_id"] == "wcrp"
    assert wcrp["cv_version"] == "esgvoc-1.4.2"
    assert wcrp["backfilled"] is True


def test_compliance_failure_carries_a_single_line_reason():
    report = {
        "tasks": [
            _task(
                "seaIce.siconc.tavg-u-hxy-si.mon.glb",
                compliance={
                    "passed": False,
                    "failed_checks": "[ATTR001] branch_time_in_parent missing\nand more\nand more",
                    "environment_warning": False,
                },
            )
        ]
    }

    wcrp = gates_from_report(report)["seaIce.siconc.tavg-u-hxy-si.mon.glb"]["wcrp"]

    assert wcrp["result"] == "fail"
    assert wcrp["message"] == "[ATTR001] branch_time_in_parent missing (+2 more)"


def test_an_incomplete_checker_environment_downgrades_a_pass_to_a_warning():
    """A checker that ran without its vocabulary database did not really pass.

    Recording it as a clean pass would claim an audit that never happened.
    """
    report = {
        "tasks": [
            _task(
                "land.gpp.tavg-u-hxy-lnd.mon.glb",
                compliance={"passed": True, "environment_warning": True},
            )
        ]
    }

    wcrp = gates_from_report(report)["land.gpp.tavg-u-hxy-lnd.mon.glb"]["wcrp"]

    assert wcrp["result"] == "warn"
    assert wcrp["environment_warning"] is True
    assert "did not run" in wcrp["message"]


def test_compliance_without_a_verdict_is_ignored():
    report = {"tasks": [_task("atmos.tas.tavg-h2m-hxy-u.mon.glb", compliance={"note": "hi"})]}

    assert gates_from_report(report) == {}


# ── The batch-level qc fallback, for older reports ──────────────────────────


BATCH_QC = {
    "total": 3,
    "passed": 1,
    "warned": 1,
    "failed": 1,
    "warnings": [
        {
            "file": "/scratch/out/tos.nc",
            "variable_id": "tos",
            "warning": "outside allowed range",
            "observed_range": [-2.1, 34.8],
            "allowed_range": [-2.0, 34.0],
            "units": "degC",
        }
    ],
    "failures": [
        {"file": "/scratch/out/siconc.nc", "variable_id": "siconc", "error": "all values missing"}
    ],
}


def _fallback_report():
    return {
        "qc": BATCH_QC,
        "tasks": [
            _task("atmos.tas.tavg-h2m-hxy-u.mon.glb", files=["/scratch/out/tas.nc"]),
            _task("ocean.tos.tavg-u-hxy-sea.mon.glb", files=["/scratch/out/tos.nc"]),
            _task("seaIce.siconc.tavg-u-hxy-si.mon.glb", files=["/scratch/out/siconc.nc"]),
        ],
    }


@pytest.mark.parametrize(
    ("variable", "expected"),
    [
        ("atmos.tas.tavg-h2m-hxy-u.mon.glb", "pass"),
        ("ocean.tos.tavg-u-hxy-sea.mon.glb", "warn"),
        ("seaIce.siconc.tavg-u-hxy-si.mon.glb", "fail"),
    ],
)
def test_batch_qc_block_is_matched_to_tasks_by_output_path(variable, expected):
    """A file the QC pass scanned and did not report is a pass, not an unknown."""
    gates = gates_from_report(_fallback_report())

    assert gates[variable]["range"]["result"] == expected


def test_batch_qc_fallback_carries_the_observed_range():
    gates = gates_from_report(_fallback_report())

    assert gates["ocean.tos.tavg-u-hxy-sea.mon.glb"]["range"]["observed"] == [-2.1, 34.8]
    assert gates["ocean.tos.tavg-u-hxy-sea.mon.glb"]["range"]["units"] == "degC"


def test_a_task_with_no_known_output_files_gets_no_range_gate():
    """Without a file path there is no way to know whether it was scanned."""
    report = {"qc": BATCH_QC, "tasks": [_task("atmos.tas.tavg-h2m-hxy-u.mon.glb")]}

    assert gates_from_report(report) == {}


def test_stamped_gates_win_over_the_fallback():
    report = {
        "qc": BATCH_QC,
        "tasks": [
            _task(
                "ocean.tos.tavg-u-hxy-sea.mon.glb",
                gates={"range": {"result": "pass"}},
                files=["/scratch/out/tos.nc"],
            )
        ],
    }

    gates = gates_from_report(report)

    assert gates["ocean.tos.tavg-u-hxy-sea.mon.glb"]["range"]["result"] == "pass"


# ── The record ──────────────────────────────────────────────────────────────


def test_build_qc_record_returns_none_when_there_is_nothing_to_record():
    report = {"tasks": [_task("atmos.tas.tavg-h2m-hxy-u.mon.glb")]}

    assert build_qc_record("ACCESS-ESM1.6", "historical", "r1i1p1f1", report) is None


def test_build_qc_record_validates_against_the_schema():
    import json

    import jsonschema

    report = {
        "tasks": [
            _task(
                "atmos.tas.tavg-h2m-hxy-u.mon.glb",
                gates={"range": {"result": "pass"}, "repack": {"result": "pass"}},
                compliance={"passed": True, "cv_version": "esgvoc-1.4.2"},
            )
        ]
    }
    record = build_qc_record(
        "ACCESS-ESM1.6", "historical", "r1i1p1f1", report,
        source_report="moppy_batch_report_20260826T120000Z.json",
        checked_by="ingest_report.py",
    )

    schema_path = Path(__file__).parent.parent / "schemas" / "qc.schema.json"
    jsonschema.validate(record, json.loads(schema_path.read_text()))
