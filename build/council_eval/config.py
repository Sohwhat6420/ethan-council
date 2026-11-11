"""Paths and exclusion rules. Nothing here is secret; the alias table, the HMAC key and the
owner's own exclusion lists live in local/ (git-ignored) and are never published."""
from __future__ import annotations

import json
import os
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BUILD_DIR / "data"          # git-ignored: scrubbed benchmark rows
LOCAL_DIR = BUILD_DIR / "local"        # git-ignored: alias table, HMAC key, exclusions.json
RESULTS_DIR = BUILD_DIR / "results"    # aggregate results; *.json git-ignored

TRANSCRIPTS_ROOT = Path(os.path.expanduser("~")) / ".claude" / "projects"

# Transcript folders never read (substring match on the folder name).
# Generic defaults; add the owner's own (any project that holds other people's data, minors' above all)
# in local/exclusions.json as {"project_substrings": [...], "text_patterns": [...]}.
_DEFAULT_PROJECT_SUBSTRINGS = (
    "AppData-Local-Temp",       # scratch sessions of lanes and subagents, not the owner's own rulings
    "anthropic-runs",           # unattended API runs
    "jobs-",                    # background job sessions
)

# A benchmark row is dropped (not redacted) when its text matches any of these.
# Case-insensitive regexes; keep them broad: a false drop costs one row, a false keep can leak someone else's data.
_DEFAULT_TEXT_PATTERNS = (
    r"\bnric\b",
    r"\bminors?\b",
    r"\bunder.?18\b",
)

EXCLUSIONS_FILE = LOCAL_DIR / "exclusions.json"


def _load_exclusions(path: Path = EXCLUSIONS_FILE) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not path.exists():
        return _DEFAULT_PROJECT_SUBSTRINGS, _DEFAULT_TEXT_PATTERNS
    extra = json.loads(path.read_text(encoding="utf-8"))
    return (_DEFAULT_PROJECT_SUBSTRINGS + tuple(extra.get("project_substrings", ())),
            _DEFAULT_TEXT_PATTERNS + tuple(extra.get("text_patterns", ())))


EXCLUDED_PROJECT_SUBSTRINGS, EXCLUDE_TEXT_PATTERNS = _load_exclusions()

DEFAULT_ALIAS_FILE = LOCAL_DIR / "aliases.json"   # {"Name or nickname": "ROLE"}; ROLE in PEER, AUTHORITY, FAMILY, PARTNER, OTHER
DEFAULT_KEY_FILE = LOCAL_DIR / "pseudonym.key"     # random 32 bytes, created on first use

RECOMMENDED_MARKERS = ("(recommended)", "[recommended]", "recommended:")
