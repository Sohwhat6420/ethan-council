"""Metrics for the Scrutiniser benchmark. Pure Python, no SciPy.

- accuracy with a Wilson 95 per cent interval
- chance level (mean of 1/number-of-options) and lift over chance
- follow / override subsets: rows where he took the recommended option versus rows where he overrode it.
  Override accuracy is the number that shows whether a model has learnt HIM rather than learnt "pick the recommended"
- exact McNemar test between two arms on the same rows
- paired bootstrap interval for the accuracy difference
- Brier score and expected calibration error when an arm returns probabilities
"""
from __future__ import annotations

import math
import random
from typing import Sequence


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def mcnemar_exact(a_correct: Sequence[bool], b_correct: Sequence[bool]) -> dict:
    """Two-sided exact binomial McNemar on discordant pairs."""
    assert len(a_correct) == len(b_correct)
    b = sum(1 for x, y in zip(a_correct, b_correct) if x and not y)   # A right, B wrong
    c = sum(1 for x, y in zip(a_correct, b_correct) if y and not x)   # B right, A wrong
    n = b + c
    if n == 0:
        return {"a_only": 0, "b_only": 0, "p": 1.0}
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return {"a_only": b, "b_only": c, "p": min(1.0, 2 * tail)}


def paired_bootstrap_diff(a_correct: Sequence[bool], b_correct: Sequence[bool], iters: int = 2000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(a_correct)
    if n == 0:
        return (0.0, 0.0)
    diffs = []
    for _ in range(iters):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(b_correct[i] - a_correct[i] for i in idx) / n)
    diffs.sort()
    return (diffs[int(0.025 * iters)], diffs[int(0.975 * iters) - 1])


def brier(probs: Sequence[Sequence[float]], gold: Sequence[int]) -> float:
    tot = 0.0
    for p, g in zip(probs, gold):
        tot += sum((pi - (1.0 if i == g else 0.0)) ** 2 for i, pi in enumerate(p))
    return tot / max(1, len(gold))


def ece(probs: Sequence[Sequence[float]], gold: Sequence[int], bins: int = 10) -> float:
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for p, g in zip(probs, gold):
        conf = max(p)
        pred = max(range(len(p)), key=lambda i: p[i])
        buckets[min(bins - 1, int(conf * bins))].append((conf, pred == g))
    n = max(1, len(gold))
    return sum(len(b) / n * abs(sum(c for c, _ in b) / len(b) - sum(ok for _, ok in b) / len(b)) for b in buckets if b)


def summarise(rows: Sequence[dict], preds: Sequence[int | None], cue: Sequence[bool] | None = None) -> dict:
    correct = [p is not None and p == r["answer_idx"] for r, p in zip(rows, preds)]
    n = len(rows)
    k = sum(correct)
    chance = sum(1 / len(r["options"]) for r in rows) / n if n else 0.0
    fol = [c for r, c in zip(rows, correct) if r.get("rec_idx") is not None and r["answer_idx"] == r["rec_idx"]]
    ovr = [c for r, c in zip(rows, correct) if r.get("rec_idx") is not None and r["answer_idx"] != r["rec_idx"]]
    unparsed = sum(1 for p in preds if p is None)
    lo, hi = wilson(k, n)
    out = {
        "n": n, "accuracy": k / n if n else 0.0, "ci95": [lo, hi], "chance": chance,
        "lift_over_chance": (k / n - chance) if n else 0.0,
        "follow_n": len(fol), "follow_acc": (sum(fol) / len(fol)) if fol else None,
        "override_n": len(ovr), "override_acc": (sum(ovr) / len(ovr)) if ovr else None,
        "unparsed": unparsed,
    }
    if cue is not None:   # BUILD-PLAN U9: the score without the rows whose prompt once carried a residual cue
        no_cue = [c for c, q in zip(correct, cue) if not q]
        out.update({"cue_n": sum(1 for q in cue if q),
                    "accuracy_no_cue": (sum(no_cue) / len(no_cue)) if no_cue else None})
    return out


# Pre-registered pass thresholds for the LoRA arm (BUILD-PLAN section 5, 10 Nov 2026), measured on the frozen
# 375-row test split, shuffled and blind. The override floor is the amendment he accepted on 10 Nov
# ("Accept the extra rule (Recommended)"): the gain must not come from imitating Claude's recommendation.
GATES = {
    "baseline_arm": "A1 qwen3:4b zero-shot, 10 Nov 2026",
    "baseline_acc": 0.656,          # the better of A1 (65.6%) and A2 (61.1%)
    "primary_min_acc": 0.706,       # baseline + 5 points
    "mcnemar_p_max": 0.05,          # paired against the baseline's per-item file
    "override_min_acc": 0.245,      # the accepted amendment: A2's measured override accuracy
    "override_target_acc": 0.35,    # reported, not gated alone (n = 53)
    "baseline_follow_acc": 0.799,
    "follow_max_drop": 0.05,
    "unparsed_max_frac": 0.01,
    "canary_leaks_max": 0,
}


def gates(summary: dict, compare: dict | None = None, canary: dict | None = None, g: dict = GATES) -> dict:
    """Apply the pre-registered gates to one arm's shuffled-blind summary.

    `compare` is run_eval.compare()'s output with this arm as "b" and the baseline as "a" (for the McNemar p);
    without it the significance criterion is reported as unknown and the overall verdict cannot pass."""
    n = max(1, summary.get("n", 0))
    checks = {
        "primary_accuracy": {"value": summary.get("accuracy"), "min": g["primary_min_acc"],
                             "pass": (summary.get("accuracy") or 0.0) >= g["primary_min_acc"]},
        "mcnemar_vs_baseline": {"value": compare["mcnemar"]["p"] if compare else None, "max": g["mcnemar_p_max"],
                                "pass": bool(compare) and compare["mcnemar"]["p"] < g["mcnemar_p_max"]
                                and compare["acc_b"] > compare["acc_a"]},
        "override_floor_amendment": {"value": summary.get("override_acc"), "min": g["override_min_acc"],
                                     "pass": (summary.get("override_acc") or 0.0) >= g["override_min_acc"]},
        "follow_no_worse_than_baseline_minus_5": {
            "value": summary.get("follow_acc"), "min": g["baseline_follow_acc"] - g["follow_max_drop"],
            "pass": (summary.get("follow_acc") or 0.0) >= g["baseline_follow_acc"] - g["follow_max_drop"]},
        "unparsed_at_most_1pct": {"value": summary.get("unparsed", 0) / n, "max": g["unparsed_max_frac"],
                                  "pass": summary.get("unparsed", 0) / n <= g["unparsed_max_frac"]},
        "canary_zero_leaks": {"value": canary["leaked"] if canary else None, "max": g["canary_leaks_max"],
                              "pass": bool(canary) and canary["leaked"] <= g["canary_leaks_max"]},
    }
    report = {"checks": checks, "override_target_reported": {"value": summary.get("override_acc"), "target": g["override_target_acc"]},
              "all_pass": all(c["pass"] for c in checks.values())}
    report["verdict"] = ("PASS: the LoRA beats the no-training arms without imitating Claude" if report["all_pass"]
                         else "FAIL: ship retrieval plus prompt (A2); report the negative result")
    return report
