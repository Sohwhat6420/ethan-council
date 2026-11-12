"""Stage 6: build the Scrutiniser training view (chat-format JSONL) from train.jsonl only.

The last 10 per cent of train by time becomes the validation file (early stopping on the AMD run).
Canary rows are mixed into the training file (not validation) for the stage 7 audit.
view.json records the prompt version and owner name the view was rendered with; the training script renders the
test prompts with the same pair and refuses to run if the training rows disagree with it.
Output files stay in build/data/ (git-ignored) and are uploaded to the AMD box only after the owner's review-gate approval:
see the approval check below.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from . import config
from .approval import check_approval
from .canary import canary_rows, make_canaries
from .ingest import read_jsonl, write_jsonl
from .prompts import render, shuffled, system, target

VIEW_FILE = "view.json"


def to_chat(row: dict, blind: bool = True, prompt: str | None = None, owner: str | None = None) -> dict:
    """TRL conversational prompt-completion format: loss falls on the completion (the answer) only.

    With a plain "messages" row the loss covered the whole prompt and the one-token answer was a tiny share of it
    (found in the CPU smoke run, 10 Nov)."""
    return {"prompt": [
        {"role": "system", "content": system(prompt, owner)},
        {"role": "user", "content": render(row, blind=blind, version=prompt, owner=owner)},
    ], "completion": [{"role": "assistant", "content": target(row)}], "id": row["id"]}


def view_settings(prompt: str | None = None, owner: str | None = None) -> dict:
    cfg = config.settings()
    return {"prompt": prompt or cfg["prompt"], "owner": owner if owner is not None else cfg["owner"]}


def write_view(data_dir: Path, view: dict) -> None:
    (data_dir / VIEW_FILE).write_text(json.dumps(view, indent=1), encoding="utf-8")


def read_view(data_dir: Path) -> dict | None:
    p = data_dir / VIEW_FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def build(train: list[dict], val_frac: float = 0.1, n_canaries: int = 5, seed: int = 0, prompt: str | None = None,
          owner: str | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    v = view_settings(prompt, owner)
    prompt, owner = v["prompt"], v["owner"]
    train = sorted(train, key=lambda r: r["ts"])
    n_val = max(1, int(len(train) * val_frac)) if len(train) > 10 else 0
    tr, va = train[: len(train) - n_val], train[len(train) - n_val:]
    canaries = make_canaries(n_canaries)
    # Train on shuffled options so the adapter cannot learn "the first option is the answer".
    rows = [to_chat(shuffled(r, seed), prompt=prompt, owner=owner) for r in tr] + canary_rows(canaries, system(prompt, owner))
    random.Random(seed).shuffle(rows)
    return rows, [to_chat(shuffled(r, seed), prompt=prompt, owner=owner) for r in va], canaries


def approval_file(data_dir: Path) -> Path:
    """The approval sits beside the data: <data>/../local/review-gate-approval.json (the training script's rule too)."""
    return data_dir.parent / "local" / "review-gate-approval.json"


def approved(data_dir: Path = config.DATA_DIR) -> bool:
    """True only when the owner's approval exists AND its SHA-256s match the files now on disk (BUILD-PLAN U10)."""
    return check_approval(approval_file(data_dir), data_dir)[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=config.DATA_DIR)
    ap.add_argument("--canaries", type=int, default=5)
    ap.add_argument("--prompt", choices=("v0", "v1"), default=None, help="prompt version (default: local/council.json, else v1)")
    a = ap.parse_args(argv)
    view = view_settings(a.prompt)
    tr, va, can = build(read_jsonl(a.data / "train.jsonl"), n_canaries=a.canaries, prompt=view["prompt"], owner=view["owner"])
    write_jsonl(a.data / "sft_train.jsonl", tr)
    write_jsonl(a.data / "sft_val.jsonl", va)
    (a.data / "canaries.json").write_text(json.dumps(can, indent=1), encoding="utf-8")
    write_view(a.data, view)
    ok, why = check_approval(approval_file(a.data), a.data)
    print(json.dumps({"sft_train": len(tr), "sft_val": len(va), "canaries": len(can), "prompt": view["prompt"],
                      "review_gate_approved": ok, "approval_state": why,
                      "note": "do not train or upload until review_gate_approved is true (the owner's signed, hash-bound approval)"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
