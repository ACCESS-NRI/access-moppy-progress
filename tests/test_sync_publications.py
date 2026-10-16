"""Tests for marking variables published from a listing of /g/data/im55/publications."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import sync_publications  # noqa: E402
from compile_progress import (  # noqa: E402
    _compile_unit_summary,
    _effective_publication_status,
    _unit_state,
)

DRS = "MIP-DRS7/CMIP7/CMIP/ACCESS-Consortium/ACCESS-ESM1-6/piControl/r1i1p1f1"
TAS = f"{DRS}/glb/mon/tas/tavg-h2m-hxy-u/g115/v20261001"
IDENTITY = ("ACCESS-ESM1.6", "piControl", "r1i1p1f1")


@pytest.fixture
def progress(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_publications, "PROGRESS", tmp_path)
    return tmp_path


def _listing(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "published.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_a_published_directory_resolves_to_its_branded_name(progress):
    published = sync_publications.parse_listing(_listing(progress, TAS))

    assert published == {IDENTITY: {"atmos.tas.tavg-h2m-hxy-u.mon.glb": "v20261001"}}


def test_login_noise_and_unknown_variables_are_skipped(progress, capsys):
    unknown = f"{DRS}/glb/mon/notavar/tavg-u-hxy-u/g115/v20261001"
    published = sync_publications.parse_listing(
        _listing(progress, "Loading conda/analysis3-26.09", unknown)
    )

    assert published == {}
    assert "no planned or reported variable" in capsys.readouterr().err


def test_the_latest_version_is_recorded(progress):
    older = TAS.replace("v20261001", "v20260901")
    published = sync_publications.parse_listing(_listing(progress, TAS, older))

    assert published[IDENTITY]["atmos.tas.tavg-h2m-hxy-u.mon.glb"] == "v20261001"


def test_sync_is_idempotent_and_withdraws_what_left_the_tree(progress):
    published = sync_publications.parse_listing(_listing(progress, TAS))

    assert sync_publications.sync(published, dry_run=False)["created"] == 1
    assert sync_publications.sync(published, dry_run=False)["unchanged"] == 1

    assert sync_publications.sync({}, dry_run=False)["removed"] == 1
    assert not progress.joinpath(*IDENTITY, "publication.json").exists()


def test_staging_moves_to_publications_without_losing_the_record(progress):
    staged = sync_publications.parse_listing(_listing(progress, TAS))
    dest = progress.joinpath(*IDENTITY, "publication.json")
    branded = "atmos.tas.tavg-h2m-hxy-u.mon.glb"

    assert sync_publications.sync({}, dry_run=False, staging=staged)["created"] == 1
    assert json.loads(dest.read_text())["variables"][branded]["status"] == "staging"
    assert sync_publications.sync({}, dry_run=False, staging=staged)["unchanged"] == 1

    assert sync_publications.sync(staged, dry_run=False, staging=staged)["updated"] == 1
    assert json.loads(dest.read_text())["variables"][branded]["status"] == "published"
    assert sync_publications.sync(staged, dry_run=False)["unchanged"] == 1

    assert sync_publications.sync({}, dry_run=False)["removed"] == 1
    assert not dest.exists()


def test_a_hand_written_record_is_left_alone(progress):
    dest = progress.joinpath(*IDENTITY, "publication.json")
    dest.parent.mkdir(parents=True)
    dest.write_text(json.dumps({"updated_by": "someone", "variables": {}}), encoding="utf-8")

    published = sync_publications.parse_listing(_listing(progress, TAS))
    counts = sync_publications.sync(published, dry_run=False)
    sync_publications.sync({}, dry_run=False)

    assert counts["manual"] == 1
    assert json.loads(dest.read_text())["updated_by"] == "someone"


def test_publication_without_a_cmorisation_record_still_counts():
    assert _effective_publication_status(None, "published") == "published"
    assert _effective_publication_status(None, "staging") == "staging"
    assert _effective_publication_status("failed", "published") == "not_published"
    assert _unit_state(None, {}, "staging") == "staging"


def test_staging_without_a_report_appears_in_the_compiled_units():
    branded = "atmos.tas.tavg-h2m-hxy-u.mon.glb"
    result = _compile_unit_summary(
        *IDENTITY, "*", None,
        {"variables": {branded: {"status": "staging"}}},
        None, False, {},
        {branded: {"request_name": "Amon.tas", "short_name": "tas", "cmip7_name": branded}},
    )

    assert result is not None
    units, summary = result
    assert units[0]["state"] == "staging"
    assert units[0]["publication_status"] == "staging"
    assert units[0]["location"] == "staging"
    assert summary["staging"] == 1


def test_incoming_report_is_distinct_from_publication():
    branded = "atmos.tas.tavg-h2m-hxy-u.mon.glb"
    cmor = {"source_location": "incoming", "tasks": [{"variable": branded, "status": "completed"}]}
    qc = {"variables": {branded: {
        gate: {"result": "pass"} for gate in ("range", "wcrp", "repack")
    }}}
    units, summary = _compile_unit_summary(
        "ACCESS-ESM1.6", "amip", "r1i1p1f1", "*", cmor, None,
        qc, False, {}, {},
    )

    assert units[0]["state"] == "ready_for_review"
    assert units[0]["publication_status"] == "not_published"
    assert units[0]["location"] == "incoming"
    assert summary["incoming"] == 1

    published = {"variables": {branded: {"status": "published"}}}
    units, summary = _compile_unit_summary(
        "ACCESS-ESM1.6", "amip", "r1i1p1f1", "*", cmor, published,
        qc, False, {}, {},
    )
    assert units[0]["location"] == "published"
    assert summary["incoming"] == 0
