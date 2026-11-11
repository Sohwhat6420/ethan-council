"""Stage 5 review gate: write a LOCAL review sheet for him, and record his approval.

  python -m council_eval.review_sheet            # writes build/local/review-sheet-<date>.md (git-ignored)
  python -m council_eval.review_sheet --approve "his note"   # only when HE has read the sheet and says yes

The sheet shows the scrub counts and a random sample of scrubbed rows (including free-text answers), so he can see
what would be trained on. Nothing trains, and nothing is uploaded, until local/review-gate-approval.json says approved.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .approval import APPROVAL_FILES, hashes, write_approval
from .ingest import read_jsonl


def sheet(rows: list[dict], n: int = 25, seed: int = 0, data_dir: Path | None = None) -> str:
    rng = random.Random(seed)
    counts: Counter = Counter()
    for r in rows:
        counts.update(r.get("scrub_counts") or {})
    kinds = Counter(r["answer_kind"] for r in rows)
    out = [f"# Review sheet, {datetime.now().date().isoformat()} (local only, never commit or upload)", "",
           f"Rows: {len(rows)}. By answer kind: {dict(kinds)}. Redactions and pseudonyms applied: {dict(counts)}.", "",
           "This sheet samples rulings.jsonl, the full scrubbed corpus. The training view (sft_train.jsonl, single-choice "
           "rows only, options shuffled) is a SUBSET of it, so what you review here is a superset of what would train.", "",
           "Check: any real name, phone, email, key, school or work secret, or anything about a minor that survived. "
           "If you find one, add it to build/local/aliases.json or tell Claude which pattern to add, then rebuild.", ""]
    if data_dir is not None:
        h = hashes(data_dir)
        out += ["Files your approval would be bound to (SHA-256; rebuilding any of them voids the approval):"]
        out += [f"- {f}: {h.get(f, 'MISSING')}" for f in APPROVAL_FILES]
        out.append("")
    for kind in ("option", "other", "multi"):
        pool = [r for r in rows if r["answer_kind"] == kind]
        for r in rng.sample(pool, min(n, len(pool))):
            out.append(f"## [{kind}] {r['ts'][:10]} {r['header']}")
            out.append(r["question"])
            for i, o in enumerate(r["options"]):
                mark = " <= his answer" if r.get("answer_idx") == i or i in (r.get("answer_set") or []) else ""
                out.append(f"- {o['label']}: {o['description']}{mark}")
            if r.get("answer_text"):
                out.append(f"- his own words: {r['answer_text']}")
            out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", type=Path, default=config.DATA_DIR / "rulings.jsonl")
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--data", type=Path, default=config.DATA_DIR, help="folder holding the training files to bind the approval to")
    ap.add_argument("--approve", metavar="NOTE", help="record HIS approval of the cleaned corpus (his words)")
    a = ap.parse_args(argv)
    config.LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    if a.approve:
        p = config.LOCAL_DIR / "review-gate-approval.json"
        doc = write_approval(p, a.data, a.approve)   # binds the approval to the SHA-256 of the training files (U10)
        print(f"approval recorded: {p}; bound to {sorted(doc['sha256'])}")
        return 0
    rows = read_jsonl(a.inp)
    p = config.LOCAL_DIR / f"review-sheet-{datetime.now().date().isoformat()}.md"
    p.write_text(sheet(rows, a.n, data_dir=a.data if a.data.exists() else None), encoding="utf-8")
    print(f"review sheet written (local, git-ignored): {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
