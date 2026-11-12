"""Predictor arms. Each takes a row and returns (choice index or None, probabilities or None).

A0 baselines: recommended, first, random, position prior (learnt from train).
A1 local base model, zero-shot (Ollama on this laptop; never a cloud API: the rows are the owner's data).
A2 local base model plus retrieval of the owner's k most similar past rulings (TF-IDF, pure Python, from train only).
A4 the LoRA arm runs on a GPU box via train/train_lora_amd.py and writes the same per-item file format.

The LLM call path (OWASP LLM Top 10): rows are untrusted text, so the prompt is fenced (prompts.py, LLM01); the model
can only ever return an option index (LLM05); it has no tools (LLM06); the Ollama host must be loopback, so rows never
leave the machine (LLM02); every call has a timeout, a reply-length cap and a context cap (LLM10).
"""
from __future__ import annotations

import ipaddress
import json
import math
import os
import random
import re
import urllib.parse
import urllib.request
from collections import Counter
from typing import Callable, Protocol

from . import config
from .prompts import parse_choice, render, system


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


DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
MAX_PROMPT_CHARS = 24000          # about 6,000 tokens: far above any fenced v1 prompt, a backstop for v0 and shots
MAX_REPLY_BYTES = 64 * 1024


def loopback_host(host: str | None = None) -> str:
    """The Ollama base URL, which must point at this machine (PRIVACY-PIPELINE.md rule 1: rows never leave it).

    Taken from the argument, else COUNCIL_OLLAMA_HOST, else 127.0.0.1:11434. A host without a scheme gets http://.
    Anything that is not localhost or a loopback IP is refused rather than silently sending the owner's data away."""
    raw = (host or os.environ.get("COUNCIL_OLLAMA_HOST") or DEFAULT_OLLAMA_HOST).strip()
    if "://" not in raw:
        raw = "http://" + raw
    u = urllib.parse.urlsplit(raw)
    name = (u.hostname or "").lower()
    try:
        ok = name == "localhost" or ipaddress.ip_address(name).is_loopback
    except ValueError:
        ok = False
    if u.scheme not in ("http", "https") or not ok or u.username or u.password:
        raise ValueError(f"refusing non-loopback model host {u.scheme}://{name}: the owner's rows must stay on this machine")
    return f"{u.scheme}://{u.netloc}".rstrip("/")


def ollama_chat(model: str, system: str, user: str, host: str | None = None, timeout: int = 120,
                n_options: int | None = None, max_prompt_chars: int | None = MAX_PROMPT_CHARS) -> str:
    # The local qwen3:4b build ignores think=false and /no_think and reasons in plain content (probed 10 Nov),
    # so the reply is constrained by a JSON schema: {"choice": <int>}. parse_choice reads the integer and is the
    # real guard; the schema's minimum/maximum (sent when n_options is known) is a hint the server may ignore.
    base = loopback_host(host)
    if max_prompt_chars is not None and len(system) + len(user) > max_prompt_chars:
        raise ValueError(f"prompt of {len(system) + len(user)} characters exceeds {max_prompt_chars}")
    choice: dict = {"type": "integer"}
    if n_options:
        choice.update(minimum=1, maximum=int(n_options))
    body = json.dumps({
        "model": model, "stream": False, "think": False,
        "format": {"type": "object", "properties": {"choice": choice}, "required": ["choice"]},
        "options": {"temperature": 0, "num_predict": 24, "num_ctx": 4096},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(base + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(MAX_REPLY_BYTES + 1)
    if len(raw) > MAX_REPLY_BYTES:
        raise ValueError("model reply too large")
    content = (json.loads(raw).get("message") or {}).get("content")
    return content if isinstance(content, str) else ""


class LocalLLM:
    """A1 (k=0) or A2 (k>0, retrieval over train). chat_fn is injectable for tests.

    `prompt` and `owner` default to config.settings(). Arm names gain a "-v1" suffix under the v1 prompt, so result
    files from the two prompt versions are never confused; v0 names match the published result files."""
    def __init__(self, model: str, train: list[dict] | None = None, k: int = 0, blind: bool = True,
                 chat_fn: Callable[[str, str, str], str] | None = None, prompt: str | None = None,
                 owner: str | None = None):
        cfg = config.settings()
        self.model, self.k, self.blind = model, k, blind
        self.prompt, self.owner = prompt or cfg["prompt"], owner if owner is not None else cfg["owner"]
        self.system = system(self.prompt, self.owner)   # validates the version early
        self.index = TfidfIndex(train) if (k and train) else None
        self.chat = chat_fn
        self.name = (f"{'A2-retrieval' if k else 'A1-zero-shot'}-{model}{'-blind' if blind else '-sighted'}"
                     + ("" if self.prompt == "v0" else f"-{self.prompt}"))

    def __call__(self, row):
        shots = self.index.top(row, self.k) if self.index else None
        user = render(row, blind=self.blind, shots=shots, version=self.prompt, owner=self.owner)
        n = len(row["options"])
        if self.chat is not None:
            out = self.chat(self.model, self.system, user)
        elif self.prompt == "v0":   # exactly the published request: no schema bounds, no size cap
            out = ollama_chat(self.model, self.system, user, max_prompt_chars=None)
        else:
            out = ollama_chat(self.model, self.system, user, n_options=n)
        return parse_choice(out, n), None
