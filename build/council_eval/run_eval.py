"""Score arms on the held-out split and compare them. Prints aggregates only, never row text.

  python -m council_eval.run_eval --arms recommended,first,random,prior
  python -m council_eval.run_eval --arms llm --model qwen3:4b --k 0 --limit 200
  python -m council_eval.run_eval --compare results/a.json results/b.json

Per-item files hold hashed row ids and correctness only, so arms can be paired for McNemar without row text.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date
from pathlib import Path

from . import config
from .ingest import read_jsonl
from .metrics import gates, mcnemar_exact, paired_bootstrap_diff, summarise
from .predictors import First, LocalLLM, PositionPrior, RandomChoice, Recommended
from .prompts import item, row_has_cue, shuffled


def build_arm(name: str, train: list[dict], a: argparse.Namespace):
    if name == "recommended":
        return Recommended()
    if name == "first":
        return First()
    if name == "random":
        return RandomChoice(a.seed)
    if name == "prior":
        return PositionPrior(train)
    if name == "llm":
        return LocalLLM(a.model, train=train, k=a.k, blind=not a.sighted)
    raise SystemExit(f"unknown arm {name}")


def sample(rows: list[dict], limit: int | None, seed: int) -> list[dict]:
    if not limit or limit >= len(rows):
        return rows
    rng = random.Random(seed)
    return sorted(rng.sample(rows, limit), key=lambda r: r["ts"])


def run_arm(arm, rows: list[dict]) -> tuple[dict, list[dict]]:
    preds, items, t0 = [], [], time.time()
    for r in rows:
        p = None
        for attempt in range(3):   # a local server hiccup must not kill a long run, nor count as a wrong answer
            try:
                p, _ = arm(r)
                break
            except Exception as e:
                print(f"warn: {type(e).__name__} (attempt {attempt + 1})", file=sys.stderr)
                time.sleep(2 * (attempt + 1))
        preds.append(p)
        items.append(item(r, p))
    s = summarise(rows, preds, cue=[row_has_cue(r) for r in rows])
    s.update({"arm": arm.name, "seconds": round(time.time() - t0, 1)})
    return s, items


def compare(fa: Path, fb: Path) -> dict:
    A, B = json.loads(fa.read_text(encoding="utf-8")), json.loads(fb.read_text(encoding="utf-8"))
    ia = {x["id"]: x["correct"] for x in A["items"]}
    ib = {x["id"]: x["correct"] for x in B["items"]}
    common = sorted(set(ia) & set(ib))
    ac, bc = [ia[i] for i in common], [ib[i] for i in common]
    return {"a": A["summary"]["arm"], "b": B["summary"]["arm"], "n_paired": len(common),
            "acc_a": sum(ac) / max(1, len(ac)), "acc_b": sum(bc) / max(1, len(bc)),
            "diff_b_minus_a_ci95": paired_bootstrap_diff(ac, bc), "mcnemar": mcnemar_exact(ac, bc)}


def gate_report(baseline: Path, arm: Path, canary: Path | None = None) -> dict:
    """BUILD-PLAN step 12: the pre-registered gates (section 5, with the accepted override-floor amendment) applied
    to a LoRA arm's shuffled-blind result file, paired against the baseline's per-item file."""
    B = json.loads(arm.read_text(encoding="utf-8"))
    c = compare(baseline, arm)
    can = json.loads(canary.read_text(encoding="utf-8")) if canary else None
    return {"compare": c, "gates": gates(B["summary"], c, can)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=config.DATA_DIR)
    ap.add_argument("--split", default="test")
    ap.add_argument("--arms", default="recommended,first,random,prior")
    ap.add_argument("--model", default="qwen3:4b")
    ap.add_argument("--k", type=int, default=0)
    ap.add_argument("--sighted", action="store_true", help="keep (Recommended) markers in the prompt")
    ap.add_argument("--shuffle", action="store_true", help="permute options per row (primary judgement metric)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=config.RESULTS_DIR)
    ap.add_argument("--compare", nargs=2, type=Path)
    ap.add_argument("--gates", nargs=2, type=Path, metavar=("BASELINE", "ARM"),
                    help="apply the pre-registered gates to ARM's shuffled result, paired with BASELINE")
    ap.add_argument("--canary", type=Path, help="canary-leak.json for --gates")
    a = ap.parse_args(argv)
    if a.compare:
        print(json.dumps(compare(*a.compare), indent=1))
        return 0
    if a.gates:
        rep = gate_report(a.gates[0], a.gates[1], a.canary)
        print(json.dumps(rep, indent=1))
        return 0 if rep["gates"]["all_pass"] else 1
    train = read_jsonl(a.data / "train.jsonl")
    rows = sample(read_jsonl(a.data / f"{a.split}.jsonl"), a.limit, a.seed)
    if a.shuffle:
        train = [shuffled(r, a.seed) for r in train]
        rows = [shuffled(r, a.seed) for r in rows]
    a.out.mkdir(parents=True, exist_ok=True)
    for name in a.arms.split(","):
        arm = build_arm(name.strip(), train, a)
        s, items = run_arm(arm, rows)
        s.update({"split": a.split, "limit": a.limit, "seed": a.seed, "shuffle": a.shuffle, "date": date.today().isoformat()})
        tag = ("-shuf" if a.shuffle else "") + (f"-n{a.limit}" if a.limit else "")
        path = a.out / f"{date.today().isoformat()}-{arm.name.replace(':', '_')}-{a.split}{tag}.json"
        path.write_text(json.dumps({"summary": s, "items": items}, indent=1), encoding="utf-8")
        print(json.dumps(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
