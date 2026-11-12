"""`council ask`: the council's suggestion for a question an agent is asking you. It never answers for you.

  council ask question.json --model qwen3:4b          # AskUserQuestion input: {"questions": [...]}
  echo '{"question": "...", "options": [...]}' | council ask - --model qwen3:4b
  council ask question.json --model qwen3:4b --k 4    # add your 4 most similar past rulings (needs data/train.jsonl)

The question is shown in full with the suggestion beside it, for you to accept or change (docs/PRIOR-ART.md: the
auto-answer design never answers silently). The question text is untrusted input from an agent, so it goes through
the same fenced v1 prompt as the benchmark (OWASP LLM01), only to a model on this machine (LLM02), and the reply can
only select one of the offered options (LLM05). Until a Scrutiniser adapter passes the gates, the model is an
untrained base model: treat its suggestion as a weak hint.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config
from .ingest import read_jsonl
from .predictors import LocalLLM, loopback_host

MAX_INPUT_BYTES = 256 * 1024
MAX_QUESTIONS = 4        # AskUserQuestion's own limit
MAX_OPTIONS = 10


def _rows(doc) -> list[dict]:
    """Accept AskUserQuestion input ({"questions": [...]}), one question object, or a list of them."""
    if isinstance(doc, dict) and isinstance(doc.get("questions"), list):
        qs = doc["questions"]
    elif isinstance(doc, dict):
        qs = [doc]
    elif isinstance(doc, list):
        qs = doc
    else:
        raise ValueError("expected a JSON object or list")
    if not 1 <= len(qs) <= MAX_QUESTIONS:
        raise ValueError(f"expected 1 to {MAX_QUESTIONS} questions, got {len(qs)}")
    rows = []
    for i, q in enumerate(qs):
        if not isinstance(q, dict) or not isinstance(q.get("question"), str):
            raise ValueError(f"question {i + 1}: needs a 'question' string")
        opts = q.get("options")
        if not isinstance(opts, list) or not 2 <= len(opts) <= MAX_OPTIONS:
            raise ValueError(f"question {i + 1}: needs 2 to {MAX_OPTIONS} options")
        options = []
        for o in opts:
            if isinstance(o, str):
                o = {"label": o}
            if not isinstance(o, dict) or not isinstance(o.get("label"), str):
                raise ValueError(f"question {i + 1}: each option needs a 'label' string")
            options.append({"label": o["label"], "description": str(o.get("description") or "")})
        rows.append({"id": f"ask-{i}", "header": str(q.get("header") or ""), "question": q["question"],
                     "options": options, "multi": bool(q.get("multiSelect"))})
    return rows


def suggest(doc, model: str, k: int = 0, train: list[dict] | None = None, chat_fn=None) -> list[dict]:
    arm = LocalLLM(model, train=train, k=k, blind=True, chat_fn=chat_fn)
    out = []
    for r in _rows(doc):
        if r["multi"]:
            out.append({"question": r["question"], "options": r["options"], "suggested": None,
                        "note": "multi-select questions are not scored yet"})
            continue
        idx, _ = arm(r)
        out.append({"question": r["question"], "header": r["header"], "options": r["options"],
                    "suggested": None if idx is None else idx + 1,
                    "suggested_label": None if idx is None else r["options"][idx]["label"]})
    return out


def _print(results: list[dict]) -> None:
    for res in results:
        print(("[" + res["header"] + "] " if res.get("header") else "") + res["question"])
        for i, o in enumerate(res["options"], 1):
            mark = "  <- council" if res.get("suggested") == i else ""
            print(f"  {i}. {o['label']}" + (f" - {o['description']}" if o["description"] else "") + mark)
        if res.get("note"):
            print(f"  ({res['note']})")
        elif res["suggested"] is None:
            print("  (no usable suggestion from the model; decide as usual)")
        else:
            print("  The council's pick is a suggestion: accept it or choose another.")
        print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="council ask", description="Suggest which option you would pick. Never answers for you.")
    ap.add_argument("file", help="JSON file with the question(s), or - for stdin")
    ap.add_argument("--model", default="qwen3:4b", help="local Ollama model (default qwen3:4b)")
    ap.add_argument("--k", type=int, default=0, help="add your k most similar past rulings from --data/train.jsonl")
    ap.add_argument("--data", type=Path, default=config.DATA_DIR)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    raw = (sys.stdin.buffer.read(MAX_INPUT_BYTES + 1) if a.file == "-" else Path(a.file).read_bytes()[: MAX_INPUT_BYTES + 1])
    if len(raw) > MAX_INPUT_BYTES:
        print(f"input larger than {MAX_INPUT_BYTES} bytes", file=sys.stderr)
        return 2
    try:
        doc = json.loads(raw.decode("utf-8"))
        _rows(doc)
        loopback_host()
    except (ValueError, UnicodeDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    train = None
    if a.k:
        f = a.data / "train.jsonl"
        if not f.exists():
            print(f"error: --k needs {f} (run council ingest and council split first)", file=sys.stderr)
            return 2
        train = read_jsonl(f)
    try:
        results = suggest(doc, a.model, a.k, train)
    except OSError as e:   # URLError and timeouts: no local model server
        print(f"error: could not reach the local model ({type(e).__name__}). Is Ollama running? "
              f"Try: ollama pull {a.model}", file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps(results, indent=1, ensure_ascii=False))
    else:
        _print(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
