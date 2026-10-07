"""Tests for marking variables published from a listing of /g/data/im55/publications."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import sync_publications  # noqa: E402
from compile_progress import _effective_publication_status  # noqa: E402

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
    assert _effective_publication_status("failed", "published") == "not_published"
