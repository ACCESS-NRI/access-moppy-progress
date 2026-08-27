"""Tests for picking the report to ingest out of an rsynced Gadi tree.

The layout on Gadi is the one the sync workflow pulls: a run directory holding
``batch_config.yml`` next to the live report, with superseded reports moved
into an ``archives/`` subdirectory of that same run directory.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from sync_reports import collect_latest, run_directory  # noqa: E402

IDENTITY = ("ACCESS-ESM1.6", "1pctCO2", "r1i1p1f1")


def _iso(stamp: str) -> str:
    """The ISO created_at a MOPPy report carries for a given filename stamp."""
    return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").isoformat() + "+00:00"


def _report(directory: Path, stamp: str, **overrides) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    report = {
        "source_id": "ACCESS-ESM1-6",
        "experiment_id": "1pctCO2",
        "variant_label": "r1i1p1f1",
        "created_at": _iso(stamp),
    }
    report.update(overrides)
    report = {key: value for key, value in report.items() if value is not None}
    path = directory / f"moppy_batch_report_{stamp}.json"
    path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    return path


def _run_dir(source: Path, name: str) -> Path:
    directory = source / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "batch_config.yml").write_text(
        "source_id: ACCESS-ESM1-6\nexperiment_id: 1pctCO2\nvariant_label: r1i1p1f1\n",
        encoding="utf-8",
    )
    return directory


def test_archived_report_does_not_shadow_the_live_one(tmp_path):
    """An archives/ subdirectory is the same run, so the newest report still wins."""
    run = _run_dir(tmp_path, "1pctCO2-01")
    _report(run / "archives", "20260819T064139Z")
    latest = _report(run, "20260827T053037Z")

    collected = collect_latest(tmp_path)

    assert IDENTITY in collected, "the archived report masked the live one"
    assert collected[IDENTITY][0] == latest


def test_two_run_directories_resolve_by_recency(tmp_path):
    """A job rerun under a fresh run directory: the newest report wins."""
    _report(_run_dir(tmp_path, "1pctCO2-01"), "20260819T064139Z")
    newest = _report(_run_dir(tmp_path, "1pctCO2-02"), "20260827T053037Z")

    collected = collect_latest(tmp_path)

    assert collected[IDENTITY][0] == newest


def test_recency_wins_regardless_of_directory_order(tmp_path):
    """The newest report is taken even when it sits in the first directory read."""
    newest = _report(_run_dir(tmp_path, "1pctCO2-01"), "20260827T053037Z")
    _report(_run_dir(tmp_path, "1pctCO2-02"), "20260819T064139Z")

    collected = collect_latest(tmp_path)

    assert collected[IDENTITY][0] == newest


def test_a_collision_is_reported_naming_the_report_taken(tmp_path, capsys):
    _report(_run_dir(tmp_path, "1pctCO2-01"), "20260819T064139Z")
    newest = _report(_run_dir(tmp_path, "1pctCO2-02"), "20260827T053037Z")

    collect_latest(tmp_path)

    err = capsys.readouterr().err
    assert "COLLISION ACCESS-ESM1.6/1pctCO2/r1i1p1f1" in err
    assert str(newest) in err


def test_an_iso_created_at_outranks_an_older_filename_stamp(tmp_path):
    """Mixed timestamp forms are compared as instants, not as text.

    An ISO created_at sorts below a bare filename stamp as a string whatever
    the dates say, so a report with only a filename stamp would always win.
    """
    _report(_run_dir(tmp_path, "1pctCO2-01"), "20260819T064139Z", created_at=None)
    newest = _report(_run_dir(tmp_path, "1pctCO2-02"), "20260827T053037Z")

    collected = collect_latest(tmp_path)

    assert collected[IDENTITY][0] == newest


def test_a_filename_stamp_outranks_an_older_iso_created_at(tmp_path):
    """The same comparison the other way round: text order would flip this one."""
    _report(_run_dir(tmp_path, "1pctCO2-01"), "20260819T064139Z")
    newest = _report(_run_dir(tmp_path, "1pctCO2-02"), "20260827T053037Z", created_at=None)

    collected = collect_latest(tmp_path)

    assert collected[IDENTITY][0] == newest


def test_an_undated_report_loses_to_a_dated_one(tmp_path):
    """A report with no created_at and no filename stamp sorts oldest."""
    run = _run_dir(tmp_path, "1pctCO2-01")
    undated = _report(run, "20260827T053037Z", created_at=None)
    undated.rename(run / "moppy_batch_report_final.json")
    dated = _report(run, "20260819T064139Z")

    collected = collect_latest(tmp_path)

    assert collected[IDENTITY][0] == dated


def test_archived_report_inherits_the_run_directory_config(tmp_path):
    """An archived report predating in-report identifiers reads the run's config."""
    run = _run_dir(tmp_path, "1pctCO2-01")
    archived = _report(
        run / "archives",
        "20260819T064139Z",
        source_id=None,
        experiment_id=None,
        variant_label=None,
    )

    collected = collect_latest(tmp_path)

    assert collected[IDENTITY][0] == archived


def test_run_directory_falls_back_to_the_reports_own_directory(tmp_path):
    """With no batch_config.yml anywhere above it, a report stands on its own."""
    stray = tmp_path / "loose" / "deeper"
    path = _report(stray, "20260827T053037Z")

    assert run_directory(path, tmp_path) == stray
