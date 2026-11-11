"""One prompt format, shared by the local eval, the SFT view and the AMD training script, so train and test match."""
from __future__ import annotations

import re

from .ingest import has_recommend_cue, strip_recommended

SYSTEM = (
    "You are the Scrutiniser of the ETHAN COUNCIL: a model of how Ethan decides. "
    "Given a question Ethan was asked and the options he was offered, answer with the number of the option "
    "Ethan himself would choose. Reply with the number only."
)


def render(row: dict, blind: bool = True, shots: list[dict] | None = None) -> str:
    """blind=True removes every '(Recommended)' marker, so the model must judge rather than copy the recommendation."""
    def one(r: dict, with_answer: bool) -> str:
        lines = []
        if r.get("header"):
            lines.append(f"[{r['header']}]")
        lines.append("Question: " + (strip_recommended(r["question"]) if blind else r["question"]))
        for i, o in enumerate(r["options"], 1):
            lab = strip_recommended(o["label"]) if blind else o["label"]
            desc = strip_recommended(o["description"]) if blind else o["description"]
            lines.append(f"{i}. {lab}" + (f" - {desc}" if desc else ""))
        if with_answer:
            # The chosen option's TEXT, not its number: with numbers, the 4B model copied the shots' answer
            # positions (A2 v0 on 10 Nov: 58.1% vs 65.6% zero-shot, McNemar p = 0.009).
            chosen = r["options"][r["answer_idx"]]["label"]
            lines.append("Ethan chose: " + (strip_recommended(chosen) if blind else chosen))
        return "\n".join(lines)

    parts = []
    if shots:
        parts.append("Past decisions by Ethan, for reference:\n\n" + "\n\n".join(one(s, True) for s in shots))
        parts.append("Now the new question.")
    parts.append(one(row, False))
    parts.append("Which option number would Ethan choose?")
    return "\n\n".join(parts)


def shuffled(row: dict, seed: int = 0) -> dict:
    """Permute the options deterministically per row and remap answer_idx and rec_idx.

    Claude nearly always lists its recommended option first and he follows it about 82 per cent of the time, so on
    unshuffled rows "always answer 1" scores about 79 per cent without any judgement. Shuffling removes that cue;
    the shuffled-blind score is the benchmark's primary "judgement" number.
    """
    import hashlib
    import random as _r
    n = len(row["options"])
    perm = list(range(n))
    _r.Random(int(hashlib.sha256(f"{seed}:{row['id']}".encode()).hexdigest()[:8], 16)).shuffle(perm)
    inv = {old: new for new, old in enumerate(perm)}
    out = dict(row)
    out["options"] = [row["options"][i] for i in perm]
    out["answer_idx"] = inv[row["answer_idx"]] if row.get("answer_idx") is not None else None
    out["rec_idx"] = inv[row["rec_idx"]] if row.get("rec_idx") is not None else None
    return out


def target(row: dict) -> str:
    return str(row["answer_idx"] + 1)


def row_has_cue(row: dict) -> bool:
    """Did this row's text carry a residual "recommend" cue before the 10 Nov widening (BUILD-PLAN U9)?
    Tagged per item so scores can be reported with and without such rows."""
    return any(has_recommend_cue(t) for t in [row.get("question", ""), row.get("header", "")]
               + [o.get("label", "") + " " + o.get("description", "") for o in row.get("options", [])])


def item(row: dict, pred: int | None) -> dict:
    """The harness's per-item record: hashed id, correctness, parsed flag and the cue tag. Never row text."""
    return {"id": row["id"], "correct": pred is not None and pred == row["answer_idx"], "parsed": pred is not None,
            "cue": row_has_cue(row)}


_NUM = re.compile(r"\b(\d{1,2})\b")


def parse_choice(text: str, n_options: int) -> int | None:
    text = re.sub(r"<think>.*?</think>", " ", text or "", flags=re.DOTALL)
    for m in _NUM.finditer(text):
        v = int(m.group(1))
        if 1 <= v <= n_options:
            return v - 1
    return None
