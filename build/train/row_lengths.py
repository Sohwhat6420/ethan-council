"""TRAINING-COMPUTE-PLAN U-L3: how long are the training rows under the base model's tokeniser? Counts only.

  python train/row_lengths.py --data data --base Qwen/Qwen3-1.7B

Prints a histogram of token lengths (prompt plus completion, chat template applied) and the share over 1024 and
1536 tokens. Never prints row text.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--base", default="Qwen/Qwen3-1.7B")
    ap.add_argument("--file", default="sft_train.jsonl")
    a = ap.parse_args(argv)
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.base)
    kw = {"enable_thinking": False} if "enable_thinking" in (tok.chat_template or "") else {}
    lens = []
    for line in (a.data / a.file).open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        ids = tok.apply_chat_template(r["prompt"] + r["completion"], tokenize=True, **kw)
        if hasattr(ids, "keys"):   # transformers 5 returns a BatchEncoding
            ids = ids["input_ids"]
        lens.append(len(ids))
    lens.sort()
    n = len(lens)
    edges = [0, 128, 256, 384, 512, 768, 1024, 1536, 2048, 4096, 10 ** 9]
    hist = {f"{lo}-{hi if hi < 10**9 else 'inf'}": sum(1 for x in lens if lo <= x < hi) for lo, hi in zip(edges, edges[1:])}
    out = {"file": a.file, "rows": n, "tokeniser": a.base, "mean": round(sum(lens) / n, 1), "median": lens[n // 2],
           "p95": lens[int(0.95 * n)], "max": lens[-1], "total_tokens": sum(lens),
           "over_1024": sum(1 for x in lens if x > 1024), "over_1536": sum(1 for x in lens if x > 1536), "histogram": hist}
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
