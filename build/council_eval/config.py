"""Paths and exclusion rules. Nothing here is secret; the alias table, the HMAC key and the
owner's own exclusion lists live in local/ (git-ignored) and are never published."""
from __future__ import annotations

import json
import os
from pathlib import Path

_SOURCE_DIR = Path(__file__).resolve().parent.parent


def _home() -> Path:
    """Where data/, local/ and results/ live.

    COUNCIL_HOME wins. In a source checkout (including `pip install -e .`) it is the checkout's build/ folder, whose
    .gitignore keeps those folders out of git. A regular install falls back to ~/.human-llm-council, never to
    site-packages."""
    env = os.environ.get("COUNCIL_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if (_SOURCE_DIR / "council_eval").is_dir() and (_SOURCE_DIR / ".gitignore").is_file():
        return _SOURCE_DIR
    return Path.home() / ".human-llm-council"


BUILD_DIR = _home()
DATA_DIR = BUILD_DIR / "data"          # git-ignored: scrubbed benchmark rows
LOCAL_DIR = BUILD_DIR / "local"        # git-ignored: alias table, HMAC key, exclusions.json, council.json
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


# Owner settings: who the council models and which prompt version it uses. Read from local/council.json
# ({"owner": "Sam", "prompt": "v1"}) with COUNCIL_OWNER and COUNCIL_PROMPT overriding. The owner's name is only ever
# sent to a local model; it is never committed.
SETTINGS_FILE = LOCAL_DIR / "council.json"
DEFAULT_OWNER = "the owner"
DEFAULT_PROMPT = "v1"


def settings(path: Path | None = None) -> dict:
    path = SETTINGS_FILE if path is None else path
    out = {"owner": DEFAULT_OWNER, "prompt": DEFAULT_PROMPT}
    if path.exists():
        doc = json.loads(path.read_text(encoding="utf-8"))
        out.update({k: v for k, v in doc.items() if k in out and isinstance(v, str) and v.strip()})
    for key, env in (("owner", "COUNCIL_OWNER"), ("prompt", "COUNCIL_PROMPT")):
        if os.environ.get(env, "").strip():
            out[key] = os.environ[env].strip()
    return out
