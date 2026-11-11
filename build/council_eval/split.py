"""Time-based split, de-duplication and the self-agreement (test-retest) set.

- Train = older rows, test = newest rows (default last 20 per cent by time). A time split, never random: the paper's
  claim is "predicts his NEXT rulings", and preferences drift over time, so a random split would be flattering.
- Duplicates: the same question with the same option labels. The first copy stays; later copies answered on a
  different day become retest pairs, and his agreement with himself on those pairs is the benchmark's ceiling.
- Leakage guard: a test row whose normalised question also appears in train is removed from test.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config
from .ingest import norm, read_jsonl, write_jsonl


def key(row: dict) -> str:
    return norm(row["question"]) + " || " + " | ".join(norm(o["label"]) for o in row["options"])


def classify_rows(rows: list[dict]) -> list[dict]:
    """Only single-select rows whose answer is one of the offered options are scorable as multiple choice."""
    return [r for r in rows if r["answer_kind"] == "option" and r["answer_idx"] is not None]


def dedupe(rows: list[dict]) -> tuple[list[dict], list[tuple[dict, dict]]]:
    first: dict[str, dict] = {}
    retest: list[tuple[dict, dict]] = []
    out = []
    for r in sorted(rows, key=lambda x: x["ts"]):
        k = key(r)
        if k in first:
            a = first[k]
            if r["ts"][:10] != a["ts"][:10]:
                retest.append((a, r))
            continue
        first[k] = r
        out.append(r)
    return out, retest


def time_split(rows: list[dict], test_frac: float = 0.2, cutoff: str | None = None) -> tuple[list[dict], list[dict]]:
    rows = sorted(rows, key=lambda x: x["ts"])
    if cutoff:
        train = [r for r in rows if r["ts"] < cutoff]
        test = [r for r in rows if r["ts"] >= cutoff]
    else:
        n_test = max(1, int(round(len(rows) * test_frac))) if rows else 0
        train, test = rows[: len(rows) - n_test], rows[len(rows) - n_test:]
    train_q = {norm(r["question"]) for r in train}
    test = [r for r in test if norm(r["question"]) not in train_q]
    return train, test


def self_agreement(pairs: list[tuple[dict, dict]]) -> dict:
    if not pairs:
        return {"pairs": 0, "agreement": None}
    same = sum(1 for a, b in pairs if a["answer_idx"] == b["answer_idx"])
    return {"pairs": len(pairs), "agreement": same / len(pairs)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Split rulings.jsonl into train/test/retest (counts only on stdout).")
    ap.add_argument("--inp", type=Path, default=config.DATA_DIR / "rulings.jsonl")
    ap.add_argument("--outdir", type=Path, default=config.DATA_DIR)
    ap.add_argument("--test-frac", type=float, default=0.2)
    ap.add_argument("--cutoff", default=None, help="ISO date; rows on or after it go to test")
    a = ap.parse_args(argv)
    rows = classify_rows(read_jsonl(a.inp))
    uniq, pairs = dedupe(rows)
    train, test = time_split(uniq, a.test_frac, a.cutoff)
    write_jsonl(a.outdir / "train.jsonl", train)
    write_jsonl(a.outdir / "test.jsonl", test)
    write_jsonl(a.outdir / "retest.jsonl", [{"a": x, "b": y} for x, y in pairs])
    summary = {
        "scorable_rows": len(rows), "unique": len(uniq), "train": len(train), "test": len(test),
        "train_span": [train[0]["ts"][:10], train[-1]["ts"][:10]] if train else None,
        "test_span": [test[0]["ts"][:10], test[-1]["ts"][:10]] if test else None,
        "self_agreement": self_agreement(pairs),
    }
    (a.outdir / "split-summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
