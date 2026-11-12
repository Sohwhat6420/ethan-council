"""Predictor arms. Each takes a row and returns (choice index or None, probabilities or None).

A0 baselines: recommended, first, random, position prior (learnt from train).
A1 local base model, zero-shot (Ollama on this laptop; never a cloud API: the rows are the owner's data).
A2 local base model plus retrieval of the owner's k most similar past rulings (TF-IDF, pure Python, from train only).
A4 the LoRA arm runs on the AMD box via train/train_lora_amd.py and writes the same per-item file format.
"""
from __future__ import annotations

import json
import math
import random
import re
import urllib.request
from collections import Counter
from typing import Callable, Protocol

from .prompts import SYSTEM, parse_choice, render


class Predictor(Protocol):
    name: str
    def __call__(self, row: dict) -> tuple[int | None, list[float] | None]: ...


class Recommended:
    name = "A0-recommended"
    def __call__(self, row):
        return (row["rec_idx"] if row.get("rec_idx") is not None else 0), None


class First:
    name = "A0-first"
    def __call__(self, row):
        return 0, None


class RandomChoice:
    name = "A0-random"
    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)
    def __call__(self, row):
        n = len(row["options"])
        return self.rng.randrange(n), [1 / n] * n


class PositionPrior:
    """Learns P(answer position | number of options, whether a recommendation exists) from train."""
    name = "A0-position-prior"
    def __init__(self, train: list[dict]):
        self.c: dict[tuple, Counter] = {}
        for r in train:
            k = (len(r["options"]), r.get("rec_idx"))
            self.c.setdefault(k, Counter())[r["answer_idx"]] += 1
    def __call__(self, row):
        k = (len(row["options"]), row.get("rec_idx"))
        if k in self.c:
            return self.c[k].most_common(1)[0][0], None
        return (row["rec_idx"] if row.get("rec_idx") is not None else 0), None


_TOK = re.compile(r"[a-z0-9]{2,}")


class TfidfIndex:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        docs = [self._toks(r) for r in rows]
        df = Counter(t for d in docs for t in set(d))
        n = max(1, len(rows))
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self.vecs = [self._vec(d) for d in docs]

    @staticmethod
    def _toks(r: dict) -> list[str]:
        return _TOK.findall((r["question"] + " " + " ".join(o["label"] for o in r["options"])).lower())

    def _vec(self, toks: list[str]) -> dict[str, float]:
        tf = Counter(toks)
        v = {t: c * self.idf.get(t, 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def top(self, row: dict, k: int) -> list[dict]:
        q = self._vec(self._toks(row))
        scored = sorted(((sum(q.get(t, 0.0) * w for t, w in v.items()), i) for i, v in enumerate(self.vecs)), reverse=True)
        return [self.rows[i] for s, i in scored[:k] if s > 0]


def ollama_chat(model: str, system: str, user: str, host: str = "http://127.0.0.1:11434", timeout: int = 120) -> str:
    # The local qwen3:4b build ignores think=false and /no_think and reasons in plain content (probed 10 Nov),
    # so the reply is constrained by a JSON schema: {"choice": <int>}. parse_choice reads the integer.
    body = json.dumps({
        "model": model, "stream": False, "think": False,
        "format": {"type": "object", "properties": {"choice": {"type": "integer"}}, "required": ["choice"]},
        "options": {"temperature": 0, "num_predict": 24, "num_ctx": 4096},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(host + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())["message"]["content"]


class LocalLLM:
    """A1 (k=0) or A2 (k>0, retrieval over train). chat_fn is injectable for tests."""
    def __init__(self, model: str, train: list[dict] | None = None, k: int = 0, blind: bool = True,
                 chat_fn: Callable[[str, str, str], str] | None = None):
        self.model, self.k, self.blind = model, k, blind
        self.index = TfidfIndex(train) if (k and train) else None
        self.chat = chat_fn or (lambda m, s, u: ollama_chat(m, s, u))
        self.name = f"{'A2-retrieval' if k else 'A1-zero-shot'}-{model}{'-blind' if blind else '-sighted'}"

    def __call__(self, row):
        shots = self.index.top(row, self.k) if self.index else None
        out = self.chat(self.model, SYSTEM, render(row, blind=self.blind, shots=shots))
        return parse_choice(out, len(row["options"])), None
