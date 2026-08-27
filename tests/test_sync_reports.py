"""Tests for picking the report to ingest out of an rsynced Gadi tree.

The layout on Gadi is the one the sync workflow pulls: a run directory holding
``batch_config.yml`` next to the live report, with superseded reports moved
into an ``archives/`` subdirectory of that same run directory.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from sync_reports import collect_latest, run_directory  # noqa: E402

IDENTITY = ("ACCESS-ESM1.6", "1pctCO2", "r1i1p1f1")


def _report(directory: Path, stamp: str, **overrides) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    report = {
        "source_id": "ACCESS-ESM1-6",
        "experiment_id": "1pctCO2",
        "variant_label": "r1i1p1f1",
        "created_at": stamp,
    }
    report.update(overrides)
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


def test_two_run_directories_claiming_one_identity_are_skipped(tmp_path):
    """A genuine collision -- two configured run directories -- is still refused."""
    _report(_run_dir(tmp_path, "1pctCO2-01"), "20260819T064139Z")
    _report(_run_dir(tmp_path, "1pctCO2-02"), "20260827T053037Z")

    assert IDENTITY not in collect_latest(tmp_path)


def test_collisions_may_be_resolved_by_recency_on_request(tmp_path):
    _report(_run_dir(tmp_path, "1pctCO2-01"), "20260819T064139Z")
    newest = _report(_run_dir(tmp_path, "1pctCO2-02"), "20260827T053037Z")

    collected = collect_latest(tmp_path, allow_collisions=True)

    assert collected[IDENTITY][0] == newest


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
