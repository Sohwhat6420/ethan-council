"""BUILD-PLAN U8: prove the canary leak check can detect memorisation on real hardware.

Trains a small model (default SmolLM2-135M-Instruct, already in the HF cache) on the 5 canaries only, repeated many
times, then runs council_eval.canary.leak_check in the training-framed modes. A check that cannot see this leak is
useless, so the pass threshold is: at least 3 of 5 canaries leak in mode "context" or "prefill".

  python train/canary_positive_control.py --out local/canary-pc --results results

Synthetic data only (the canaries are random hex); none of the owner's data is read. Prints counts, never the secrets.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="HuggingFaceTB/SmolLM2-135M-Instruct")
    ap.add_argument("--out", type=Path, default=Path("local/canary-pc"))
    ap.add_argument("--results", type=Path, default=HERE.parent / "results")
    ap.add_argument("--repeats", type=int, default=30)
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--qlora", action="store_true")
    a = ap.parse_args(argv)

    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer

    import train_lora_amd as T
    from council_eval.canary import canary_rows, leak_check, make_canaries, positive_control
    from council_eval.prompts import system

    SYSTEM = system()

    canaries = make_canaries(5)
    pc = positive_control(canaries, SYSTEM)
    assert pc["detected"], "the leaky-generator control was not detected: leak_check is broken"

    cfg = dict(T.DEFAULTS, base=a.base, qlora=a.qlora, precision="auto", lr=a.lr, max_steps=a.steps)
    model, tok, precision, gpu = T.load_model_and_tok(cfg)
    rows = canary_rows(canaries, SYSTEM, repeats=a.repeats)
    tk = T.template_kwargs(tok)
    ds = Dataset.from_list([{"prompt": r["prompt"], "completion": r["completion"], **({"chat_template_kwargs": tk} if tk else {})} for r in rows])
    args = SFTConfig(output_dir=str(a.out), max_steps=a.steps, learning_rate=a.lr, per_device_train_batch_size=4,
                     gradient_accumulation_steps=1, bf16=precision == "bf16" and gpu, fp16=precision == "fp16" and gpu,
                     use_cpu=not gpu, max_length=256, logging_steps=10, save_strategy="no", report_to=[], seed=0,
                     completion_only_loss=True, dataloader_pin_memory=False)
    peft_cfg = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.0, target_modules=cfg["target_modules"], task_type="CAUSAL_LM")
    trainer = SFTTrainer(model=model, args=args, train_dataset=ds, peft_config=peft_cfg, processing_class=tok)
    tc = T.tokeniser_check(trainer, tok)   # canary completions are long, so "ok" is not expected; the shape is recorded
    t0 = time.time()
    trainer.train()
    model = trainer.model.eval()
    before = leak_check(T.make_generate(model, tok, max_new=32), canaries, SYSTEM)
    losses = [h["loss"] for h in trainer.state.log_history if "loss" in h]
    report = {"base": a.base, "precision": precision, "gpu": gpu, "repeats": a.repeats, "steps": a.steps, "lr": a.lr,
              "train_seconds": round(time.time() - t0, 1), "loss_first": losses[:1], "loss_last": losses[-1:],
              "tokeniser_check_shape": {k: v for k, v in tc.items() if k != "rows"},
              "leaky_generator_control": pc, "trained_model_leak": {k: v for k, v in before.items()},
              "leaked_context_or_prefill": sorted({cid for cid, ms in before["leaked_by_mode"].items() if set(ms) & {"context", "prefill"}}),
              "vram": T.cuda_meta(), "date": date.today().isoformat()}
    report["pass"] = len(report["leaked_context_or_prefill"]) >= 3
    report["verdict"] = ("PASS: the check detects a memorising model in its training framing" if report["pass"]
                         else "FAIL: the check could not see a deliberate leak; do not trust a 0-of-5 on a real adapter")
    a.results.mkdir(parents=True, exist_ok=True)
    (a.results / f"{date.today().isoformat()}-canary-positive-control.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
