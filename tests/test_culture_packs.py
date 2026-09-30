import json

import pytest

from app.culture_packs.loader import list_packs, load_pack, load_scripts
from app.models import CultureSelection


def sel(**kw):
    base = dict(pack_id="majhi_punjabi", region="Amritsar", setting="rural", output_script="gurmukhi")
    return CultureSelection(**{**base, **kw})


def test_selection_has_no_defaults():
    with pytest.raises(Exception):
        CultureSelection(pack_id="majhi_punjabi")


def test_valid_selection_passes():
    sel().validate_against(load_pack("majhi_punjabi"), load_scripts())


@pytest.mark.parametrize(
    "bad", [dict(region="Ludhiana"), dict(output_script="tamil"), dict(pack_id="other")]
)
def test_invalid_selection_rejected(bad):
    with pytest.raises(ValueError):
        sel(**bad).validate_against(load_pack("majhi_punjabi"), load_scripts())


def test_new_culture_is_data_only(tmp_path):
    """Adding Malwai = dropping a JSON file. No code changes."""
    pack = {
        "id": "malwai_punjabi", "culture": "Malwai Punjabi",
        "regions": ["Bathinda"], "settings": ["rural"],
        "supported_scripts": ["gurmukhi", "devanagari"], "default_script": "devanagari",
    }
    (tmp_path / "malwai_punjabi.json").write_text(json.dumps(pack))
    loaded = load_pack("malwai_punjabi", tmp_path)
    s = sel(pack_id="malwai_punjabi", region="Bathinda", output_script="devanagari")
    s.validate_against(loaded, load_scripts())


def test_pack_with_unknown_script_fails_at_load(tmp_path):
    pack = {
        "id": "x", "culture": "X", "regions": ["r"], "settings": ["rural"],
        "supported_scripts": ["klingon"], "default_script": "klingon",
    }
    (tmp_path / "x.json").write_text(json.dumps(pack))
    with pytest.raises(ValueError):
        list_packs(tmp_path)


def test_script_detects_characters():
    g = load_scripts()["gurmukhi"]
    assert g.contains("ਸ") and not g.contains("a")
