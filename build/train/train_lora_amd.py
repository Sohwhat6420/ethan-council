"""Train and evaluate ONE Scrutiniser LoRA. BUILD-PLAN steps 9 to 12.

Runs on any CUDA or ROCm box, including this laptop's 6 GB RTX 3060 (QLoRA, 10 Nov 2026 laptop test) and the AMD
MI300X path the file was written for (bf16 LoRA). On a laptop without a GPU, --dry-run checks the data files, the
config and the review-gate approval without importing torch.

  python train/train_lora_amd.py --dry-run --data data
  python train/train_lora_amd.py --data data --base Qwen/Qwen3-1.7B --qlora --out local/adapter-v1-qlora
  python train/train_lora_amd.py --data local/syn-data --no-approval-check --qlora ...   # synthetic only

Gates (all enforced in code):
  - no training on real data without the owner's signed review-gate approval whose SHA-256s match the files on disk
    (council_eval.approval); --no-approval-check works only on a folder carrying SYNTHETIC.marker;
  - the canary leak check is positive-controlled first: a deliberately leaky generator MUST be detected, else exit 4;
  - a canary leak in the trained adapter exits 3;
  - the pre-registered pass thresholds (council_eval.metrics.GATES, with the override-floor amendment the owner accepted on
    10 Nov) are applied when --baseline names the A1 per-item result file.

Writes: the adapter (safetensors only), test-item results in the harness's per-item format
(results/<date>-A4-lora-<base>[-qlora]-test[-shuf].json), canary-leak.json, gates.json and run-meta.json (VRAM
peak, s/step, total time; counts and metrics only, never row text).
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from council_eval.approval import check_approval, is_synthetic  # noqa: E402

DEFAULTS = {
    "base": "Qwen/Qwen3-4B",        # Apache-2.0 (audit 10 Nov); laptop fallback Qwen/Qwen3-1.7B
    "lora_r": 16, "lora_alpha": 32, "lora_dropout": 0.05,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "lr": 2e-4, "epochs": 2, "max_len": 1536, "batch": 8, "grad_accum": 2, "precision": "auto", "seed": 0,
    "qlora": False, "grad_ckpt": False, "optim": "adamw_torch", "max_steps": -1,
}
QLORA_DEFAULTS = {"batch": 2, "grad_accum": 8, "grad_ckpt": True, "optim": "paged_adamw_8bit"}   # 6 GB laptop card


def check(data: Path, require_approval: bool = True) -> dict:
    report: dict = {"ok": True, "problems": [], "synthetic": is_synthetic(data)}
    for f in ("sft_train.jsonl", "sft_val.jsonl", "test.jsonl", "canaries.json"):
        if not (data / f).exists():
            report["ok"] = False
            report["problems"].append(f"missing {f}")
    if report["ok"]:
        tr = [json.loads(l) for l in (data / "sft_train.jsonl").open(encoding="utf-8") if l.strip()]
        bad = [i for i, r in enumerate(tr)
               if [m["role"] for m in r.get("prompt", []) + r.get("completion", [])] != ["system", "user", "assistant"]]
        if bad:
            report["ok"] = False
            report["problems"].append(f"{len(bad)} malformed chat rows")
        chars = sum(len(m["content"]) for r in tr for m in r["prompt"] + r["completion"])
        report.update({"train_rows": len(tr), "canary_rows": sum(1 for r in tr if r.get("canary")),
                       "approx_tokens": chars // 4,
                       "test_rows": sum(1 for l in (data / "test.jsonl").open(encoding="utf-8") if l.strip())})
    appr = data.parent / "local" / "review-gate-approval.json"
    if require_approval:
        ok, why = check_approval(appr, data)
        report["approval"] = why
        if not ok:
            report["ok"] = False
            report["problems"].append(why)
    elif not report["synthetic"]:
        report["ok"] = False
        report["problems"].append("--no-approval-check is allowed only on a folder carrying SYNTHETIC.marker; "
                                  "real data needs the owner's hash-bound approval")
    else:
        report["approval"] = "skipped: synthetic data"
    return report


# ----------------------------------------------------------------------------------------------------------------
# Everything below needs torch. Kept in functions so the canary positive-control script can reuse them.

def resolve_precision(precision: str):  # pragma: no cover - needs torch
    import torch
    if precision == "auto":
        if torch.cuda.is_available():
            precision = "bf16" if torch.cuda.is_bf16_supported() else "fp16"
        else:
            precision = "fp32"
    dtype = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[precision]
    return precision, dtype


def load_model_and_tok(cfg: dict):  # pragma: no cover - needs torch
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(cfg["base"])
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    gpu = torch.cuda.is_available()   # ROCm builds of PyTorch report AMD GPUs through the cuda API
    precision, dtype = resolve_precision(cfg["precision"])
    kw: dict = {"dtype": dtype}
    if gpu:
        kw["device_map"] = {"": 0}
    if cfg["qlora"]:
        from transformers import BitsAndBytesConfig
        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                       bnb_4bit_compute_dtype=dtype, bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(cfg["base"], **kw)
    return model, tok, precision, gpu


def template_kwargs(tok) -> dict:
    """Qwen3 (and other hybrid-thinking templates) take enable_thinking; with it off the generation prompt ends in an
    empty <think></think> block. Passed both at training (per-row chat_template_kwargs) and at eval, so they agree."""
    return {"enable_thinking": False} if "enable_thinking" in (tok.chat_template or "") else {}


def make_generate(model, tok, max_new: int = 8):  # pragma: no cover - needs torch
    """generate(messages, prefill) -> text, the signature council_eval.canary.leak_check expects."""
    import torch
    tk = template_kwargs(tok)

    def gen(messages: list[dict], prefill: str | None = None, max_new_tokens: int = max_new) -> str:
        # transformers 5 returns a BatchEncoding here, not a tensor (smoke test 10 Nov), so ask for the dict explicitly.
        enc = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt", return_dict=True, **tk)
        ids = enc["input_ids"]
        if prefill:
            pre = tok(prefill, add_special_tokens=False, return_tensors="pt")["input_ids"]
            ids = torch.cat([ids, pre], dim=1)
        ids = ids.to(model.device)
        with torch.no_grad():
            out = model.generate(input_ids=ids, attention_mask=torch.ones_like(ids), max_new_tokens=max_new_tokens,
                                 do_sample=False, pad_token_id=tok.pad_token_id)
        return tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True)
    return gen


def tokeniser_check(trainer, tok, n: int = 3) -> dict:
    """BUILD-PLAN U7: decode the tokens TRL will put loss on. They must be exactly the answer plus the end token,
    with the chat template's think block (if any) in the masked prompt, never in the completion."""
    ds = trainer.train_dataset
    rows = []
    seen = 0
    for i in range(len(ds)):
        ex = ds[i]
        if "completion_mask" in ex:
            mask = [bool(m) for m in ex["completion_mask"]]
        elif "labels" in ex:        # TRL 1.17 folds completion_mask into labels (-100 on the prompt) and drops the column
            mask = [lab != -100 for lab in ex["labels"]]
        else:
            return {"ok": False, "why": "neither completion_mask nor labels present: completion-only loss is not active"}
        if all(mask):
            return {"ok": False, "why": "no token is masked: the loss would cover the whole prompt"}
        comp = [t for t, m in zip(ex["input_ids"], mask) if m]
        prompt_tail = [t for t, m in zip(ex["input_ids"], mask) if not m][-12:]
        text = tok.decode(comp)
        if len(text) > 40:       # a canary row: report its length only
            rows.append({"completion_tokens": len(comp), "completion_chars": len(text), "long": True})
            continue
        rows.append({"completion_tokens": len(comp), "completion": text, "prompt_tail": tok.decode(prompt_tail)})
        seen += 1
        if seen >= n:
            break
    short = [r for r in rows if not r.get("long")]
    ok = bool(short) and all(
        r["completion"].strip().rstrip(tok.eos_token or "").strip().rstrip("<|im_end|>").strip().isdigit()
        and "<think>" not in r["completion"] for r in short)
    think_in_prompt = any("</think>" in r.get("prompt_tail", "") for r in short)
    return {"ok": ok, "rows": rows, "think_block_in_masked_prompt": think_in_prompt,
            "max_completion_tokens_in_sample": max((r["completion_tokens"] for r in short), default=None)}


def cuda_meta():  # pragma: no cover - needs torch
    import torch
    if not torch.cuda.is_available():
        return {"gpu": None}
    p = torch.cuda.get_device_properties(0)
    return {"gpu": p.name, "vram_total_gb": round(p.total_memory / 2**30, 2),
            "max_allocated_gb": round(torch.cuda.max_memory_allocated() / 2**30, 3),
            "max_reserved_gb": round(torch.cuda.max_memory_reserved() / 2**30, 3)}


def versions():  # pragma: no cover - needs torch
    import torch, transformers, peft, trl  # noqa: E401
    v = {"torch": torch.__version__, "transformers": transformers.__version__, "peft": peft.__version__, "trl": trl.__version__,
         "python": platform.python_version(), "os": platform.platform()}
    try:
        import bitsandbytes
        v["bitsandbytes"] = bitsandbytes.__version__
    except Exception:
        v["bitsandbytes"] = None
    return v


def train_and_eval(a: argparse.Namespace, cfg: dict) -> int:  # pragma: no cover - needs a GPU box
    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer

    from council_eval.canary import leak_check, positive_control
    from council_eval.metrics import gates, summarise
    from council_eval.prompts import SYSTEM, item, parse_choice, render, row_has_cue, shuffled
    from council_eval.run_eval import compare

    t_start = time.time()
    meta: dict = {"config": cfg, "data": str(a.data), "synthetic": is_synthetic(a.data), "started": datetime.now(timezone.utc).isoformat()}
    model, tok, precision, gpu = load_model_and_tok(cfg)
    cfg["precision_resolved"] = precision
    meta["versions"] = versions()
    if gpu:
        torch.cuda.reset_peak_memory_stats()
    meta["after_load"] = cuda_meta()

    ds = load_dataset("json", data_files={"train": str(a.data / "sft_train.jsonl"), "validation": str(a.data / "sft_val.jsonl")})
    tk = template_kwargs(tok)
    if tk:   # TRL reads a per-row chat_template_kwargs column and passes it to apply_chat_template for prompt and prompt+completion
        ds = ds.map(lambda ex: {"chat_template_kwargs": tk})
    keep = {"prompt", "completion", "chat_template_kwargs"}
    ds = ds.remove_columns([c for c in ds["train"].column_names if c not in keep])

    peft_cfg = LoraConfig(r=cfg["lora_r"], lora_alpha=cfg["lora_alpha"], lora_dropout=cfg["lora_dropout"],
                          target_modules=cfg["target_modules"], task_type="CAUSAL_LM")
    args = SFTConfig(output_dir=str(a.out), num_train_epochs=cfg["epochs"], max_steps=cfg["max_steps"], learning_rate=cfg["lr"],
                     per_device_train_batch_size=cfg["batch"], per_device_eval_batch_size=cfg["batch"],
                     gradient_accumulation_steps=cfg["grad_accum"],
                     bf16=precision == "bf16" and gpu, fp16=precision == "fp16" and gpu, use_cpu=not gpu,
                     gradient_checkpointing=cfg["grad_ckpt"], gradient_checkpointing_kwargs={"use_reentrant": False} if cfg["grad_ckpt"] else None,
                     optim=cfg["optim"], max_length=cfg["max_len"], eval_strategy="epoch", save_strategy="epoch", save_total_limit=2,
                     load_best_model_at_end=cfg["max_steps"] < 0, logging_steps=5, seed=cfg["seed"], report_to=[],
                     completion_only_loss=True, dataloader_pin_memory=False)
    trainer = SFTTrainer(model=model, args=args, train_dataset=ds["train"], eval_dataset=ds["validation"],
                         peft_config=peft_cfg, processing_class=tok)

    tc = tokeniser_check(trainer, tok)
    meta["tokeniser_check"] = tc
    print(json.dumps({"tokeniser_check": tc}))
    if not tc["ok"]:
        print("tokeniser check failed: loss would not fall on the answer tokens only", file=sys.stderr)
        return 5
    if a.check_tokenizer:
        return 0

    t0 = time.time()
    out = trainer.train()
    train_s = time.time() - t0
    trainer.save_model(str(a.out))
    model = trainer.model.eval()
    steps = trainer.state.global_step
    losses = [h["loss"] for h in trainer.state.log_history if "loss" in h]
    evals = [h["eval_loss"] for h in trainer.state.log_history if "eval_loss" in h]
    meta["train"] = {"steps": steps, "seconds": round(train_s, 1), "s_per_step": round(train_s / max(1, steps), 3),
                     "metrics": {k: v for k, v in out.metrics.items() if isinstance(v, (int, float))},
                     "loss_first": losses[:1], "loss_last": losses[-1:], "eval_loss": evals,
                     "rows": len(ds["train"]), "effective_batch": cfg["batch"] * cfg["grad_accum"]}
    meta["after_train"] = cuda_meta()
    print(json.dumps({"train": meta["train"], "vram": meta["after_train"]}))

    gen = make_generate(model, tok, max_new=8)
    raw = [json.loads(l) for l in (a.data / "test.jsonl").open(encoding="utf-8") if l.strip()]
    if a.eval_limit:
        raw = raw[: a.eval_limit]
    res_dir = a.results
    res_dir.mkdir(parents=True, exist_ok=True)
    name = "A4-lora-" + cfg["base"].split("/")[-1] + ("-qlora" if cfg["qlora"] else "") + ("-SYNTHETIC" if meta["synthetic"] else "")
    today = date.today().isoformat()
    summaries, files = {}, {}
    t0 = time.time()
    for tag, test in (("-shuf", [shuffled(r, 0) for r in raw]), ("", raw)):   # same seed as run_eval --shuffle
        preds = [parse_choice(gen([{"role": "system", "content": SYSTEM}, {"role": "user", "content": render(r, blind=True)}]),
                              len(r["options"])) for r in test]
        s = summarise(test, preds, cue=[row_has_cue(r) for r in test])
        s.update({"arm": name, "split": "test", "shuffle": bool(tag), "date": today, "base": cfg["base"], "qlora": cfg["qlora"]})
        items = [item(r, p) for r, p in zip(test, preds)]
        f = res_dir / f"{today}-{name}-test{tag}.json"
        f.write_text(json.dumps({"summary": s, "items": items}, indent=1), encoding="utf-8")
        summaries[tag or "plain"] = s
        files[tag or "plain"] = f
    meta["eval"] = {"seconds": round(time.time() - t0, 1), "generations": 2 * len(raw), "summaries": summaries}
    print(json.dumps({"eval": summaries}))

    # Canary audit: positive control first (the check must be able to fail), then the adapter in all three modes.
    canaries = json.loads((a.data / "canaries.json").read_text(encoding="utf-8"))
    pc = positive_control(canaries, SYSTEM)
    if not pc["detected"]:
        print(json.dumps({"canary_positive_control": pc}))
        print("the canary leak check did not detect the deliberately leaky generator: check is broken", file=sys.stderr)
        return 4
    gen32 = make_generate(model, tok, max_new=32)
    leak = leak_check(lambda m, p: gen32(m, p), canaries, SYSTEM)
    leak["positive_control"] = pc
    (res_dir / f"{today}-{name}-canary-leak.json").write_text(json.dumps(leak, indent=1), encoding="utf-8")
    print(json.dumps({"canary": leak}))

    cmp = compare(a.baseline, files["-shuf"]) if a.baseline else None
    g = gates(summaries["-shuf"], cmp, leak)
    if meta["synthetic"]:
        g["note"] = "SYNTHETIC data: the gates are exercised, not meaningful"
    (res_dir / f"{today}-{name}-gates.json").write_text(json.dumps({"compare": cmp, "gates": g}, indent=1), encoding="utf-8")
    meta["gates"] = g
    meta["total_seconds"] = round(time.time() - t_start, 1)
    meta["finished"] = datetime.now(timezone.utc).isoformat()
    (res_dir / f"{today}-{name}-run-meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps({"gates": g, "total_seconds": meta["total_seconds"]}))
    return 0 if leak["pass"] else 3


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("adapter-scrutiniser-v1"))
    ap.add_argument("--results", type=Path, default=HERE.parent / "results", help="where the per-item result files go")
    ap.add_argument("--base", default=DEFAULTS["base"])
    ap.add_argument("--epochs", type=int, default=DEFAULTS["epochs"])
    ap.add_argument("--max-steps", type=int, default=DEFAULTS["max_steps"], help="stop early (smoke tests); -1 = full epochs")
    ap.add_argument("--lr", type=float, default=DEFAULTS["lr"])
    ap.add_argument("--max-len", type=int, default=DEFAULTS["max_len"])
    ap.add_argument("--precision", choices=["auto", "bf16", "fp16", "fp32"], default=DEFAULTS["precision"],
                    help="auto = bf16 where the GPU supports it, else fp16; fp32 on CPU")
    ap.add_argument("--fp32", action="store_true", help="alias for --precision fp32 (CPU smoke test)")
    ap.add_argument("--qlora", action="store_true", help="4-bit NF4 base (bitsandbytes), 8-bit paged AdamW, grad checkpointing; batch 2 x accum 8 unless given")
    ap.add_argument("--batch", type=int, default=None)
    ap.add_argument("--grad-accum", type=int, default=None)
    ap.add_argument("--grad-ckpt", dest="grad_ckpt", action="store_true", default=None)
    ap.add_argument("--no-grad-ckpt", dest="grad_ckpt", action="store_false")
    ap.add_argument("--optim", default=None)
    ap.add_argument("--baseline", type=Path, help="A1 per-item result file (shuffled) to pair the gates against")
    ap.add_argument("--eval-limit", type=int, default=None, help="evaluate the first N test rows only (smoke tests)")
    ap.add_argument("--check-tokenizer", action="store_true", help="load, run the U7 tokeniser check, exit")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-approval-check", action="store_true", help="synthetic folders only (SYNTHETIC.marker)")
    a = ap.parse_args(argv)
    cfg = dict(DEFAULTS, base=a.base, epochs=a.epochs, max_steps=a.max_steps, lr=a.lr, max_len=a.max_len,
               precision="fp32" if a.fp32 else a.precision, qlora=a.qlora)
    if a.qlora:
        cfg.update(QLORA_DEFAULTS)
    for k in ("batch", "grad_accum", "grad_ckpt", "optim"):
        if getattr(a, k) is not None:
            cfg[k] = getattr(a, k)
    rep = check(a.data, require_approval=not a.no_approval_check)
    print(json.dumps({"config": cfg, "check": rep}, indent=1))
    if not rep["ok"]:
        return 2
    if a.dry_run:
        return 0
    return train_and_eval(a, cfg)


if __name__ == "__main__":
    sys.exit(main())
