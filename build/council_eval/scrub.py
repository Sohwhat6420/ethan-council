"""Stages 2 to 4 of PRIVACY-PIPELINE.md for short text: classify, pseudonymise, redact or exclude.

Deterministic regexes plus a local alias table. A small local LLM classifier (stage 2 proper) can be added later;
this layer is the floor that always runs first and never leaves the machine.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("NRIC", re.compile(r"\b[STFGM]\d{7}[A-Z]\b")),
    ("KEY", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|xox[bpas]-[A-Za-z0-9-]{10,})\b")),
    # Long hex, or a 40+ character mixed-case alphanumeric run with a digit (slashes excluded so file paths survive).
    ("SECRET", re.compile(r"\b[A-Fa-f0-9]{32,}\b|\b(?=[A-Za-z0-9+]*\d)(?=[A-Za-z0-9+]*[a-z])(?=[A-Za-z0-9+]*[A-Z])[A-Za-z0-9+]{40,}={0,2}")),
    ("PHONE", re.compile(r"(?:\+65[\s-]?)?\b[689]\d{3}[\s-]?\d{4}\b|\+\d{1,3}[\s-]?\d{3,4}[\s-]?\d{3,4}[\s-]?\d{0,4}")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("URLQUERY", re.compile(r"(https?://[^\s?#\"')]+)\?[^\s\"')]+")),
]


@dataclass
class ScrubResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)


def _load_key(key_file: Path) -> bytes:
    if key_file.exists():
        return key_file.read_bytes()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32)
    key_file.write_bytes(key)
    return key


class Scrubber:
    def __init__(self, aliases: dict[str, str] | None = None, key: bytes | None = None,
                 exclude_patterns: tuple[str, ...] = config.EXCLUDE_TEXT_PATTERNS):
        self.key = key if key is not None else _load_key(config.DEFAULT_KEY_FILE)
        self.aliases = dict(aliases or {})
        self._exclude = [re.compile(p, re.IGNORECASE) for p in exclude_patterns]
        # Longest alias first so "Alex Example" wins over "Alex".
        names = sorted(self.aliases, key=len, reverse=True)
        self._alias_re = (re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE)
                          if names else None)
        self._lower_map = {n.lower(): n for n in self.aliases}

    @classmethod
    def from_files(cls, alias_file: Path = config.DEFAULT_ALIAS_FILE, key_file: Path = config.DEFAULT_KEY_FILE) -> "Scrubber":
        aliases = json.loads(alias_file.read_text(encoding="utf-8")) if alias_file.exists() else {}
        return cls(aliases=aliases, key=_load_key(key_file))

    def token_for(self, name: str) -> str:
        canonical = self._lower_map.get(name.lower(), name)
        role = self.aliases.get(canonical, "OTHER").upper()
        digest = hmac.new(self.key, canonical.lower().encode("utf-8"), hashlib.sha256).hexdigest()[:6]
        return f"PERSON_{digest}_{role}"

    def exclusion_reason(self, text: str) -> str | None:
        for p in self._exclude:
            if p.search(text):
                return p.pattern
        return None

    def scrub(self, text: str) -> ScrubResult:
        counts: dict[str, int] = {}
        out = text
        for label, pat in _PATTERNS:
            if label == "URLQUERY":
                out, n = pat.subn(r"\1?<QUERY>", out)
            else:
                out, n = pat.subn(f"<{label}>", out)
            if n:
                counts[label] = counts.get(label, 0) + n
        if self._alias_re is not None:
            def repl(m: re.Match[str]) -> str:
                counts["NAME"] = counts.get("NAME", 0) + 1
                return self.token_for(m.group(1))
            out = self._alias_re.sub(repl, out)
        return ScrubResult(out, counts)
