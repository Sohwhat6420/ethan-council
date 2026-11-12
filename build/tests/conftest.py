"""Every test runs with default owner settings, never the developer's own local/council.json or COUNCIL_* env."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BUILD = Path(__file__).resolve().parent.parent
for p in (BUILD, BUILD / "train"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from council_eval import config  # noqa: E402


@pytest.fixture(autouse=True)
def hermetic_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "no-such-council.json")
    for var in ("COUNCIL_OWNER", "COUNCIL_PROMPT", "COUNCIL_OLLAMA_HOST"):
        monkeypatch.delenv(var, raising=False)
