"""Stage 5 review-gate approval, bound to the exact training files by SHA-256 (BUILD-PLAN U10).

The approval file records the hash of every file that would be trained on or uploaded. If any of them is rebuilt
after he approved, the hashes differ and both make_sft.approved() and train_lora_amd.check() refuse. A path alone
(the old format) is no longer accepted.

Synthetic data (council_eval.synthetic) carries a SYNTHETIC.marker file; only such a folder may skip the gate.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

APPROVAL_FILES = ("sft_train.jsonl", "sft_val.jsonl", "test.jsonl", "canaries.json")
SYNTHETIC_MARKER = "SYNTHETIC.marker"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hashes(data_dir: Path) -> dict[str, str]:
    return {f: file_sha256(data_dir / f) for f in APPROVAL_FILES if (data_dir / f).exists()}


def write_approval(path: Path, data_dir: Path, note: str) -> dict:
    h = hashes(data_dir)
    missing = [f for f in APPROVAL_FILES if f not in h]
    if missing:
        raise FileNotFoundError(f"cannot approve: missing {missing} in {data_dir}")
    doc = {"approved": True, "note": note, "at": datetime.now(timezone.utc).isoformat(),
           "data_dir": str(data_dir), "sha256": h}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc


def check_approval(path: Path, data_dir: Path) -> tuple[bool, str]:
    """(ok, reason). ok only when the file says approved AND every recorded hash matches the file on disk now."""
    if not path.exists():
        return False, "no signed review-gate approval (PRIVACY-PIPELINE.md stage 5)"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, "approval file is not valid JSON"
    if doc.get("approved") is not True:
        return False, "approval file does not say approved"
    recorded = doc.get("sha256")
    if not isinstance(recorded, dict) or not recorded:
        return False, "approval carries no SHA-256 of the training files (old format): re-approve after review"
    now = hashes(data_dir)
    for f in APPROVAL_FILES:
        if f not in recorded:
            return False, f"approval does not cover {f}"
        if now.get(f) != recorded[f]:
            return False, f"{f} changed since approval (rebuilt?): re-review and re-approve"
    return True, "approved and hashes match"


def is_synthetic(data_dir: Path) -> bool:
    return (data_dir / SYNTHETIC_MARKER).exists()
