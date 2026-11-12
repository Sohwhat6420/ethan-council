"""Synthetic benchmark rows (no real data), for smoke-testing the training script on this laptop.

  python -m council_eval.synthetic --out build/smoke-data            # short rows: API smoke test
  python -m council_eval.synthetic --out build/local/syn-data --n 1500 --realistic   # same SHAPE as the real view

The folder gets a SYNTHETIC.marker file; only a folder with that marker may skip the review-gate approval
(train_lora_amd.py --no-approval-check). Real data can never be trained without the owner's hash-bound approval.

--realistic draws row lengths from the measured distribution of the real training view (counts only, 10 Nov:
mean about 225 tokens, 1,536 max_len) so a pipeline test on it records a VRAM peak and s/step that mean something.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from .approval import SYNTHETIC_MARKER
from .ingest import write_jsonl
from .make_sft import build, view_settings, write_view

TOPICS = ["storage", "router", "colour", "font", "model", "budget", "schedule", "name", "deploy", "backup", "layout", "test"]
_WORDS = ("the lane should keep the file local and report counts only before anything else runs tonight because "
          "memory on the host is tight and the gate stays closed until the review sheet is read then the adapter is "
          "versioned so deleting it restores the retrieval arm while the paper records the negative result").split()


def _sentence(rng: random.Random, n: int) -> str:
    return " ".join(rng.choice(_WORDS) for _ in range(n)).capitalize() + "."


def rows(n: int = 60, seed: int = 0, realistic: bool = False) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        t = rng.choice(TOPICS)
        k = rng.choice([2, 3, 4]) if not realistic else rng.choices([2, 3, 4, 5], [0.25, 0.45, 0.25, 0.05])[0]
        if realistic:
            # Target about 150 to 900 words a row (roughly 225 tokens mean, long tail), like the real rulings.
            budget = max(40, int(rng.lognormvariate(5.0, 0.6)))
            qlen = max(8, budget // (k + 2))
            opts = [{"label": f"{t.title()} option {j}: {_sentence(rng, rng.randint(3, 9))[:-1]}",
                     "description": _sentence(rng, max(6, qlen + rng.randint(-5, 15)))} for j in range(k)]
            question = _sentence(rng, qlen) + f" Which {t} setting should we use for case {i}?"
        else:
            opts = [{"label": f"{t} option {j}", "description": f"plain choice {j} about {t}"} for j in range(k)]
            question = f"Which {t} setting should we use for case {i}?"
        rec = 0
        opts[rec]["label"] += " (Recommended)"
        ans = rec if rng.random() < 0.8 else rng.randrange(k)
        out.append({"id": f"syn{i:04d}", "ts": f"2026-{7 + (i // 28) % 4:02d}-{1 + i % 28:02d}T{i % 24:02d}:00:00Z",
                    "project": "synthetic", "session": "syn", "header": t.title(), "question": question,
                    "options": opts, "multi": False, "rec_idx": rec, "answer_kind": "option", "answer_idx": ans,
                    "answer_set": [], "answer_text": "", "scrub_counts": {}})
    return out


def write(out: Path, n: int = 60, seed: int = 0, realistic: bool = False, n_canaries: int = 5,
          prompt: str | None = None) -> dict:
    r = rows(n, seed, realistic)
    train, test = r[: int(len(r) * 0.8)], r[int(len(r) * 0.8):]
    view = view_settings(prompt, owner="the owner")
    tr, va, can = build(train, n_canaries=n_canaries, prompt=view["prompt"], owner=view["owner"])
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "sft_train.jsonl", tr)
    write_jsonl(out / "sft_val.jsonl", va)
    write_jsonl(out / "test.jsonl", test)
    (out / "canaries.json").write_text(json.dumps(can, indent=1), encoding="utf-8")
    write_view(out, view)
    (out / SYNTHETIC_MARKER).write_text("synthetic rows from council_eval.synthetic; no real data\n", encoding="utf-8")
    return {"train": len(tr), "val": len(va), "test": len(test), "canaries": len(can), "realistic": realistic}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--realistic", action="store_true", help="row lengths like the real training view")
    ap.add_argument("--canaries", type=int, default=2)
    a = ap.parse_args(argv)
    print(json.dumps(write(a.out, a.n, a.seed, a.realistic, a.canaries)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
