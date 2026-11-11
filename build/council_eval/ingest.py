"""Stage 0 and 1: turn his AskUserQuestion answers in Claude Code transcripts into benchmark rows.

Why this source first: every row is a real decision he made, with the options he was offered, a timestamp, and
(usually) the option Claude recommended. That gives a clean, multiple-choice "Scrutiniser" task with a strong,
honest baseline: "he picks whatever was marked (Recommended)". A council member is only useful if it beats that.

Every text field is scrubbed before it is written. Rows that match an exclusion pattern are dropped, not redacted.
Only counts are printed; no question text is ever printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from . import config
from .scrub import Scrubber

_REC_RE = re.compile(r"\s*[\(\[]\s*recommended\s*[\)\]]\s*", re.IGNORECASE)
# Widened 10 Nov (BUILD-PLAN U9): 5 of 375 blind test prompts and 49 of 1,510 train prompts still said "recommend".
# Forms seen (counts only): "(Recommended - because ...)", "Recommended: ...", "[Recommended]", "I recommend ...",
# "the recommended ...", "my recommendation". Every form is removed; the cue must not survive in a blind prompt.
_REC_OPEN_RE = re.compile(r"([\(\[])\s*recommended\s*[\-–—:,;]?\s*", re.IGNORECASE)   # "(Recommended - x)" -> "(x)"
_REC_LEAD_RE = re.compile(r"^\s*recommended\s*[:\-–—]\s*", re.IGNORECASE)              # "Recommended: x" -> "x"
_REC_TAIL_RE = re.compile(r"\s*[\-–—:,;]\s*recommended\s*\.?\s*$", re.IGNORECASE)      # "x - Recommended" -> "x"
_REC_WORD_RE = re.compile(r"\b(?:not\s+|un)?recommend\w*\b", re.IGNORECASE)                       # any remaining stem
_SPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_PUNCT_RE = re.compile(r"\s+([,.;:?!\)\]])")
_EMPTY_BRACKET_RE = re.compile(r"\(\s*\)|\[\s*\]")


def has_recommend_cue(s: str) -> bool:
    """True if the text still contains the stem "recommend" after the ORIGINAL (bracket-only) strip. Used to tag
    rows whose blind prompt once carried a residual cue, so results can be reported with and without them."""
    return bool(_REC_WORD_RE.search(_REC_RE.sub(" ", s or "")))


def strip_recommended(s: str) -> str:
    if not s:
        return s
    s = _REC_RE.sub(" ", s)
    s = _REC_OPEN_RE.sub(r"\1", s)
    s = _REC_LEAD_RE.sub("", s)
    s = _REC_TAIL_RE.sub("", s)
    s = _REC_WORD_RE.sub("", s)
    s = _EMPTY_BRACKET_RE.sub("", s)
    s = _SPACE_PUNCT_RE.sub(r"\1", s)
    return _SPACE_RE.sub(" ", s).strip()


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", strip_recommended(s)).strip().lower()


@dataclass
class Row:
    id: str
    ts: str
    project: str
    session: str
    header: str
    question: str
    options: list[dict]          # [{"label": str, "description": str}] with recommendation markers kept
    multi: bool
    rec_idx: int | None          # index of the option marked (Recommended), if any
    answer_kind: str             # option | multi | other | declined
    answer_idx: int | None       # for kind=option
    answer_set: list[int] = field(default_factory=list)   # for kind=multi
    answer_text: str = ""        # scrubbed free text, for kind=other only
    scrub_counts: dict = field(default_factory=dict)


def _rec_index(options: list[dict]) -> int | None:
    for i, o in enumerate(options):
        lab = (o.get("label") or "").lower()
        desc = (o.get("description") or "").lower().lstrip()
        if any(m in lab for m in config.RECOMMENDED_MARKERS) or desc.startswith("recommended"):
            return i
    return None


def match_answer(answer: str, options: list[dict], multi: bool) -> tuple[str, int | None, list[int]]:
    a = norm(answer)
    labels = [norm(o.get("label") or "") for o in options]
    if a in labels:
        return "option", labels.index(a), []
    if multi:
        parts = [norm(p) for p in re.split(r",\s*", answer)]
        idxs = [labels.index(p) for p in parts if p in labels]
        if idxs and len(idxs) == len(parts):
            return "multi", None, sorted(set(idxs))
    if not a:
        return "declined", None, []
    return "other", None, []


def iter_transcript_files(root: Path) -> Iterator[Path]:
    for d in sorted(root.iterdir()) if root.exists() else []:
        if not d.is_dir() or any(s in d.name for s in config.EXCLUDED_PROJECT_SUBSTRINGS):
            continue
        yield from sorted(d.glob("*.jsonl"))


def _events(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"AskUserQuestion"' not in line and '"answers"' not in line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def extract_from_events(events: Iterable[dict], project: str) -> Iterator[dict]:
    """Yield raw joined records {tool_use_id, ts, session, questions, answers} from one transcript."""
    uses: dict[str, dict] = {}
    for ev in events:
        if ev.get("isSidechain"):
            continue
        content = (ev.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use" and c.get("name") == "AskUserQuestion":
                uses[c.get("id")] = {"ts": ev.get("timestamp", ""), "session": ev.get("sessionId", ""),
                                     "questions": (c.get("input") or {}).get("questions") or []}
            elif c.get("type") == "tool_result" and c.get("tool_use_id") in uses:
                tur = ev.get("toolUseResult")
                if not isinstance(tur, dict) or not isinstance(tur.get("answers"), dict):
                    continue
                u = uses.pop(c["tool_use_id"])
                yield {"tool_use_id": c["tool_use_id"], "ts": ev.get("timestamp") or u["ts"],
                       "session": u["session"], "project": project,
                       "questions": tur.get("questions") or u["questions"], "answers": tur["answers"]}


def rows_from_record(rec: dict, scrubber: Scrubber, stats: Counter) -> Iterator[Row]:
    answers = {norm(k): v for k, v in rec["answers"].items()}
    for qi, q in enumerate(rec["questions"]):
        qtext = q.get("question") or ""
        options = [{"label": o.get("label") or "", "description": o.get("description") or ""} for o in q.get("options") or []]
        if len(options) < 2:
            stats["skip_lt2_options"] += 1
            continue
        ans = answers.get(norm(qtext))
        if ans is None:
            stats["skip_no_answer"] += 1
            continue
        if isinstance(ans, list):   # some versions store multi-select answers as a list
            ans = ", ".join(str(x) for x in ans)
        ans = str(ans)
        blob = " ".join([qtext, q.get("header") or "", ans] + [o["label"] + " " + o["description"] for o in options])
        if scrubber.exclusion_reason(blob):
            stats["drop_excluded"] += 1
            continue
        multi = bool(q.get("multiSelect"))
        kind, idx, aset = match_answer(str(ans), options, multi)
        counts: Counter = Counter()

        def s(t: str) -> str:
            r = scrubber.scrub(t)
            counts.update(r.counts)
            return r.text

        row = Row(
            id=hashlib.sha256(f"{rec['tool_use_id']}:{qi}".encode()).hexdigest()[:16],
            ts=rec["ts"], project=rec["project"],
            session=hashlib.sha256(rec["session"].encode()).hexdigest()[:12],
            header=s(q.get("header") or ""), question=s(qtext),
            options=[{"label": s(o["label"]), "description": s(o["description"])} for o in options],
            multi=multi, rec_idx=_rec_index(options), answer_kind=kind, answer_idx=idx, answer_set=aset,
            answer_text=s(str(ans)) if kind == "other" else "", scrub_counts=dict(counts),
        )
        stats["kind_" + kind] += 1
        stats.update({"scrub_" + k: v for k, v in counts.items()})
        yield row


def ingest(root: Path, scrubber: Scrubber, limit_files: int | None = None) -> tuple[list[Row], Counter]:
    stats: Counter = Counter()
    seen: set[str] = set()
    rows: list[Row] = []
    for i, f in enumerate(iter_transcript_files(root)):
        if limit_files is not None and i >= limit_files:
            break
        stats["files"] += 1
        for rec in extract_from_events(_events(f), f.parent.name):
            if rec["tool_use_id"] in seen:     # resumed or forked sessions repeat history
                stats["dup_tool_use"] += 1
                continue
            seen.add(rec["tool_use_id"])
            stats["records"] += 1
            rows.extend(rows_from_record(rec, scrubber, stats))
    rows.sort(key=lambda r: r.ts)
    return rows, stats


def write_jsonl(path: Path, rows: Iterable) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(asdict(r) if isinstance(r, Row) else r, ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the Scrutiniser benchmark from local transcripts (counts only on stdout).")
    ap.add_argument("--root", type=Path, default=config.TRANSCRIPTS_ROOT)
    ap.add_argument("--out", type=Path, default=config.DATA_DIR / "rulings.jsonl")
    ap.add_argument("--limit-files", type=int, default=None)
    a = ap.parse_args(argv)
    rows, stats = ingest(a.root, Scrubber.from_files(), a.limit_files)
    n = write_jsonl(a.out, rows)
    stats["rows_written"] = n
    stats["rows_with_rec"] = sum(1 for r in rows if r.rec_idx is not None)
    if rows:
        stats["first_ts"], stats["last_ts"] = rows[0].ts[:10], rows[-1].ts[:10]  # type: ignore[assignment]
    print(json.dumps(dict(sorted(stats.items())), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
