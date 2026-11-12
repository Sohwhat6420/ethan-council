"""The `council` command. Each subcommand is one stage of the pipeline; `council <command> --help` for its options.

  council demo                 the whole pipeline on synthetic transcripts (start here)
  council info                 version, folders, prompt settings, model host
  council ingest               your Claude Code transcripts -> scrubbed rows (data/rulings.jsonl)
  council split                rows -> train / test / retest, by time
  council eval                 score baselines or a local model; --compare, --gates
  council review               the stage 5 review sheet; --approve "note" once you have read it
  council sft                  the training view, with canaries
  council synthetic            synthetic training folders, for testing the training script
  council ask                  the council's suggestion for one agent question (never answers for you)
  council train                the LoRA training script (source checkout only; needs the [train] extra)
"""
from __future__ import annotations

import importlib
import json
import sys

from . import __version__, config

COMMANDS = {
    "demo": ("council_eval.demo", "run the whole pipeline on synthetic transcripts"),
    "ingest": ("council_eval.ingest", "transcripts to scrubbed benchmark rows"),
    "split": ("council_eval.split", "time split, de-duplication, retest pairs"),
    "eval": ("council_eval.run_eval", "score arms, compare them, apply the gates"),
    "review": ("council_eval.review_sheet", "write the review sheet or record your approval"),
    "sft": ("council_eval.make_sft", "build the training view with canaries"),
    "synthetic": ("council_eval.synthetic", "write a synthetic training folder"),
    "ask": ("council_eval.ask", "suggest an answer to one agent question"),
}


def info() -> dict:
    from .predictors import loopback_host
    s = config.settings()
    try:
        host = loopback_host()
    except ValueError as e:
        host = f"invalid: {e}"
    return {"version": __version__, "home": str(config.BUILD_DIR), "data": str(config.DATA_DIR),
            "local": str(config.LOCAL_DIR), "results": str(config.RESULTS_DIR),
            "settings_file": str(config.SETTINGS_FILE), "settings_file_exists": config.SETTINGS_FILE.exists(),
            "prompt": s["prompt"], "owner_name_set": s["owner"] != config.DEFAULT_OWNER, "model_host": host,
            "transcripts_root": str(config.TRANSCRIPTS_ROOT)}


def _train(argv: list[str]) -> int:
    train_dir = config._SOURCE_DIR / "train"
    if not (train_dir / "train_lora_amd.py").exists():
        print("council train needs a source checkout (build/train/ is not installed with the package).", file=sys.stderr)
        return 2
    sys.path.insert(0, str(train_dir))
    import train_lora_amd   # noqa: E402  (imports torch only when it actually trains)
    return train_lora_amd.main(argv)


def usage() -> str:
    lines = [f"Human LLM Council {__version__}", "", "usage: council <command> [options]", "", "commands:"]
    lines += [f"  {name:<10} {desc}" for name, (_, desc) in COMMANDS.items()]
    lines += [f"  {'info':<10} show version, folders and prompt settings",
              f"  {'train':<10} train a LoRA adapter (source checkout, [train] extra)",
              f"  {'version':<10} print the version", "", "Start with: council demo"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in ("version", "--version", "-V"):
        print(__version__)
        return 0
    if cmd == "info":
        print(json.dumps(info(), indent=1))
        return 0
    if cmd == "train":
        return _train(rest)
    if cmd not in COMMANDS:
        print(f"unknown command {cmd!r}\n\n{usage()}", file=sys.stderr)
        return 2
    mod = importlib.import_module(COMMANDS[cmd][0])
    return int(mod.main(rest) or 0)


if __name__ == "__main__":
    sys.exit(main())
