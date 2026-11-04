"""The catalogue is the provider's documentation, so the tests read it as data.

Every entry carries `api_path`, because Higgsfield submits each model to its own
path. That is the one Higgsfield-specific rule worth pinning here; the shared
conformance suite checks the rest.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine_higgsfield.catalog import CATEGORY_DIRS, load_catalog  # noqa: E402


def test_the_catalogue_parses_and_has_both_families():
    catalog = load_catalog()
    assert len(catalog) >= 80, f"only {len(catalog)} entries — the scrape lost pages"
    image = [spec for spec in catalog.specs() if spec.category == "IMG"]
    video = [spec for spec in catalog.specs() if spec.category == "VID"]
    assert image and video, "an engine with one family is suspicious; check the scrape"


def test_every_entry_declares_the_path_it_submits_to():
    missing = [
        spec.id
        for spec in load_catalog().specs()
        if not spec.api_path
    ]
    assert not missing, f"these entries have no api_path, so the Engine cannot submit them: {missing}"


def test_every_category_matches_its_folder_and_its_kind():
    for spec in load_catalog().specs():
        assert spec.category in CATEGORY_DIRS
        assert spec.kind == ("video" if spec.category == "VID" else "image")
        assert spec.prompt_mode in ("required", "optional", "none")


def test_every_status_is_evidence_based():
    catalog = load_catalog()
    states = {catalog.status(spec.model) for spec in catalog.specs()}
    assert states <= {"experimental", "beta", "proven"}
    # Soul standard proved one call on 2026-11-04; the rest are unproven, honestly.
    assert catalog.status("higgsfield/higgsfield-ai-soul-standard") == "beta"
    assert states == {"experimental", "beta"}
