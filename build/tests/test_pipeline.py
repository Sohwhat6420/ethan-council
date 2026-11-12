"""Tests on synthetic transcripts only. No real data is read."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BUILD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUILD))
sys.path.insert(0, str(BUILD / "train"))

from council_eval import approval, config, ingest, make_sft, metrics, predictors, prompts, run_eval, split, synthetic  # noqa: E402
from council_eval.canary import (USER_TURN, canary_rows, leak_check, leaky_generator, make_canaries,  # noqa: E402
                                 positive_control, probe_messages)
from council_eval.scrub import Scrubber  # noqa: E402

KEY = b"k" * 32


def scrubber(**kw):
    return Scrubber(aliases={"Alex Example": "PEER", "Jo": "AUTHORITY"}, key=KEY, **kw)


def ask_events(tid, ts, questions, answers, sidechain=False):
    use = {"timestamp": ts, "sessionId": "s1", "isSidechain": sidechain, "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "AskUserQuestion", "input": {"questions": questions}}]}}
    res = {"timestamp": ts, "sessionId": "s1", "isSidechain": sidechain,
           "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": "The user answered"}]},
           "toolUseResult": {"questions": questions, "answers": answers}}
    return [use, res]


def q(text, labels, multi=False):
    return {"question": text, "header": "H", "multiSelect": multi,
            "options": [{"label": l, "description": "d " + l} for l in labels]}


def write_transcript(root: Path, project: str, events: list[dict]) -> None:
    d = root / project
    d.mkdir(parents=True, exist_ok=True)
    with (d / "t.jsonl").open("a", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")


# ---------- scrub ----------

def test_scrub_regexes():
    s = scrubber()
    r = s.scrub("mail someone@example.com call +65 9000 0000 id S0000000A key sk-ant-abcdefghijklmnopqrstu "
                "see https://x.com/p?token=abc path C:/Users/someone/projects/councilresearchfolder/x")
    assert "<EMAIL>" in r.text and "<PHONE>" in r.text and "<NRIC>" in r.text and "<KEY>" in r.text
    assert "https://x.com/p?<QUERY>" in r.text
    assert "councilresearchfolder" in r.text, "file paths must survive the SECRET rule"


def test_pseudonyms_stable_and_role_tagged():
    s = scrubber()
    a = s.scrub("Alex Example said hi to jo").text
    b = s.scrub("alex example again").text
    tok = s.token_for("Alex Example")
    assert tok.endswith("_PEER") and tok in a and tok in b
    assert s.token_for("Jo").endswith("_AUTHORITY") and "jo" not in a.split()
    assert Scrubber(aliases={"Alex Example": "PEER"}, key=b"z" * 32).token_for("Alex Example") != tok


def test_exclusion_patterns():
    s = scrubber(exclude_patterns=config.EXCLUDE_TEXT_PATTERNS + (r"\bXYZ club\b",))
    assert s.exclusion_reason("the XYZ club parade list")
    assert s.exclusion_reason("a roster of minors")
    assert s.exclusion_reason("Which router should we use?") is None


# ---------- ingest ----------

def test_ingest_join_match_and_exclusion(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EXCLUDED_PROJECT_SUBSTRINGS", config.EXCLUDED_PROJECT_SUBSTRINGS + ("Excluded-Project",))
    root = tmp_path / "projects"
    ev = []
    ev += ask_events("t1", "2026-10-01T01:00:00Z",
                     [q("Pick a base?", ["Qwen (Recommended)", "Llama"]), q("Colour?", ["Gold", "Blue", "Red"])],
                     {"Pick a base?": "Qwen (Recommended)", "Colour?": "Something else entirely"})
    ev += ask_events("t2", "2026-10-02T01:00:00Z", [q("Minors parade order?", ["A", "B"])], {"Minors parade order?": "A"})
    ev += ask_events("t3", "2026-10-03T01:00:00Z", [q("Which tools?", ["Git", "Node", "Py"], multi=True)],
                     {"Which tools?": "Git, Py"})
    ev += ask_events("t4", "2026-10-04T01:00:00Z", [q("Sidechain?", ["A", "B"])], {"Sidechain?": "A"}, sidechain=True)
    ev += ask_events("t5", "2026-10-04T02:00:00Z", [q("List form?", ["Git", "Node", "Py"], multi=True)],
                     {"List form?": ["Node", "Py"]})
    write_transcript(root, "C--Users-someone-projects", ev)
    write_transcript(root, "C--Users-someone-Excluded-Project",
                     ask_events("t9", "2026-10-05T01:00:00Z", [q("x?", ["A", "B"])], {"x?": "A"}))
    write_transcript(root, "C--Users-someone-projects", ev[:2])  # duplicate history (resumed session)
    rows, stats = ingest.ingest(root, scrubber())
    by_q = {r.question: r for r in rows}
    assert by_q["Pick a base?"].answer_kind == "option" and by_q["Pick a base?"].answer_idx == 0
    assert by_q["Pick a base?"].rec_idx == 0
    assert by_q["Colour?"].answer_kind == "other" and by_q["Colour?"].answer_text
    assert by_q["Which tools?"].answer_kind == "multi" and by_q["Which tools?"].answer_set == [0, 2]
    assert by_q["List form?"].answer_kind == "multi" and by_q["List form?"].answer_set == [1, 2]
    assert "Minors parade order?" not in by_q and stats["drop_excluded"] == 1
    assert "Sidechain?" not in by_q and "x?" not in by_q
    assert stats["dup_tool_use"] == 1


def test_match_answer_ignores_recommended_marker():
    opts = [{"label": "Ship it (Recommended)", "description": ""}, {"label": "Wait", "description": ""}]
    assert ingest.match_answer("Ship it", opts, False) == ("option", 0, [])
    assert ingest.match_answer("", opts, False)[0] == "declined"


# ---------- split ----------

def mkrow(i, ts, question, ans, rec=0, n=3):
    return {"id": f"r{i}", "ts": ts, "question": question, "header": "", "answer_kind": "option",
            "options": [{"label": f"opt{j}", "description": ""} for j in range(n)], "rec_idx": rec, "answer_idx": ans}


def test_split_time_order_dedupe_retest_and_leakage():
    rows = [mkrow(i, f"2026-10-{i + 1:02d}T00:00:00Z", f"q{i}", i % 3) for i in range(10)]
    rows.append(mkrow(99, "2026-10-20T00:00:00Z", "q1", 2))  # same question as r1, later day, different answer
    uniq, pairs = split.dedupe(rows)
    assert len(uniq) == 10 and len(pairs) == 1
    assert split.self_agreement(pairs) == {"pairs": 1, "agreement": 0.0}
    train, test = split.time_split(uniq, 0.2)
    assert max(r["ts"] for r in train) < min(r["ts"] for r in test)
    leak = uniq + [mkrow(50, "2026-11-01T00:00:00Z", "q0", 1)]
    _, test2 = split.time_split(leak, 0.1)
    assert all(r["question"] != "q0" for r in test2)


# ---------- metrics ----------

def test_wilson_and_mcnemar():
    lo, hi = metrics.wilson(50, 100)
    assert 0.40 < lo < 0.41 and 0.59 < hi < 0.60
    a = [True] * 10 + [False] * 10
    b = [True] * 10 + [True] * 10
    m = metrics.mcnemar_exact(a, b)
    assert m["b_only"] == 10 and m["a_only"] == 0 and m["p"] < 0.01
    assert metrics.mcnemar_exact(a, a)["p"] == 1.0


def test_summarise_follow_override():
    rows = [mkrow(0, "t", "a", 0, rec=0), mkrow(1, "t", "b", 2, rec=0), mkrow(2, "t", "c", 1, rec=None)]
    s = metrics.summarise(rows, [0, 0, None])
    assert s["accuracy"] == pytest.approx(1 / 3)
    assert s["follow_acc"] == 1.0 and s["override_acc"] == 0.0 and s["unparsed"] == 1
    s2 = metrics.summarise(rows, [0, 0, None], cue=[True, False, False])
    assert s2["cue_n"] == 1 and s2["accuracy_no_cue"] == 0.0


def test_gates_apply_the_accepted_override_floor():
    """Section 5 with the amendment the owner accepted on 10 Nov: a Claude-imitator (71.5% overall, 0% override) must FAIL."""
    imitator = {"n": 375, "accuracy": 0.715, "override_acc": 0.0, "follow_acc": 0.95, "unparsed": 0}
    cmp_sig = {"acc_a": 0.656, "acc_b": 0.715, "mcnemar": {"p": 0.01}}
    canary_ok = {"leaked": 0}
    g = metrics.gates(imitator, cmp_sig, canary_ok)
    assert g["checks"]["primary_accuracy"]["pass"] and g["checks"]["mcnemar_vs_baseline"]["pass"]
    assert not g["checks"]["override_floor_amendment"]["pass"] and not g["all_pass"]
    learner = dict(imitator, override_acc=0.30)
    assert metrics.gates(learner, cmp_sig, canary_ok)["all_pass"]
    assert not metrics.gates(learner, None, canary_ok)["all_pass"], "no paired baseline: significance unknown, cannot pass"
    assert not metrics.gates(learner, cmp_sig, {"leaked": 1})["all_pass"], "one canary leak fails the adapter"
    assert not metrics.gates(dict(learner, follow_acc=0.70), cmp_sig, canary_ok)["all_pass"], "follow may not drop more than 5 points"
    assert metrics.GATES["override_min_acc"] == 0.245 and metrics.GATES["primary_min_acc"] == 0.706


def test_calibration():
    assert metrics.brier([[1.0, 0.0]], [0]) == 0.0
    assert metrics.ece([[0.9, 0.1]] * 10, [0] * 9 + [1]) == pytest.approx(0.0, abs=1e-9)


# ---------- prompts and predictors ----------

def test_blind_render_hides_recommendation_and_parse():
    r = mkrow(0, "t", "Pick (Recommended) one", 1)
    r["options"][0]["label"] = "Alpha (Recommended)"
    blind = prompts.render(r, blind=True)
    assert "Recommended" not in blind and "1. Alpha" in blind
    assert "Recommended" in prompts.render(r, blind=False)
    assert prompts.parse_choice("<think>9</think> 2", 3) == 1
    assert prompts.parse_choice("none", 3) is None


def test_strip_recommended_widened_removes_every_cue_form():
    """BUILD-PLAN U9: every form seen in the 10 Nov census must go, and the row is tagged as having carried a cue."""
    cases = {
        "Ship it (Recommended)": "Ship it",
        "Ship it [Recommended]": "Ship it",
        "Ship it (Recommended - fastest and safest)": "Ship it (fastest and safest)",
        "Ship it (Recommended — fastest)": "Ship it (fastest)",
        "Recommended: ship it": "ship it",
        "Ship it - Recommended": "Ship it",
        "I recommend the gold one because it matches.": "I the gold one because it matches.",
        "Claude's recommendation was option 2": "Claude's was option 2",
        "Which model do you recommend?": "Which model do you?",
        "Not recommended for a 6 GB card": "for a 6 GB card",
        "plain text": "plain text",
        "": "",
    }
    for src, want in cases.items():
        got = ingest.strip_recommended(src)
        assert "recommend" not in got.lower(), src
        assert got == want, (src, got)
    r = mkrow(0, "t", "Which do you recommend?", 0)
    assert prompts.row_has_cue(r)
    assert not prompts.row_has_cue(mkrow(1, "t", "Plain (Recommended) question", 0)), "a bracket marker alone is not a residual cue"
    assert "recommend" not in prompts.render(r, blind=True).lower()
    it = prompts.item(r, 0)
    assert it["cue"] is True and it["correct"] is True and it["parsed"] is True and set(it) == {"id", "correct", "parsed", "cue"}


def test_shuffle_remaps_answer_and_is_deterministic():
    r = mkrow(7, "t", "q", ans=2, rec=0, n=4)
    for i, o in enumerate(r["options"]):
        o["label"] = f"L{i}"
    s1, s2 = prompts.shuffled(r, 0), prompts.shuffled(r, 0)
    assert s1 == s2
    assert s1["options"][s1["answer_idx"]]["label"] == "L2"
    assert s1["options"][s1["rec_idx"]]["label"] == "L0"
    assert sorted(o["label"] for o in s1["options"]) == ["L0", "L1", "L2", "L3"]


def test_local_llm_with_retrieval_uses_injected_chat():
    train = [mkrow(i, "t", f"router question {i}", 1) for i in range(5)]
    seen = {}

    def fake_chat(model, system, user):
        seen["user"] = user
        return "2"
    arm = predictors.LocalLLM("fake", train=train, k=2, chat_fn=fake_chat)
    p, _ = arm(mkrow(9, "t", "router question new", 1))
    assert p == 1 and "Past decisions" in seen["user"] and arm.name.startswith("A2-retrieval")


def test_run_arm_and_compare(tmp_path):
    rows = [mkrow(i, f"2026-10-{i + 1:02d}", f"q{i}", 0 if i < 7 else 2) for i in range(10)]
    s1, it1 = run_eval.run_arm(predictors.Recommended(), rows)
    s2, it2 = run_eval.run_arm(predictors.PositionPrior(rows), rows)
    assert s1["accuracy"] == 0.7
    for name, s, it in (("a", s1, it1), ("b", s2, it2)):
        (tmp_path / f"{name}.json").write_text(json.dumps({"summary": s, "items": it}))
    c = run_eval.compare(tmp_path / "a.json", tmp_path / "b.json")
    assert c["n_paired"] == 10


# ---------- SFT view, canaries, AMD script ----------

def test_make_sft_and_canaries():
    train = [mkrow(i, f"2026-10-{i + 1:02d}", f"q{i}", i % 3) for i in range(20)]
    tr, va, can = make_sft.build(train, n_canaries=2)
    assert len(va) == 2 and len(can) == 2
    assert sum(1 for r in tr if r.get("canary")) == 6
    plain = [r for r in tr if not r.get("canary")]
    assert all([m["role"] for m in r["prompt"] + r["completion"]] == ["system", "user", "assistant"] for r in plain)
    assert all("Recommended" not in r["prompt"][1]["content"] for r in plain)
    assert all(r["completion"][0]["content"].isdigit() for r in plain), "the completion is the answer number only"


def test_canary_check_uses_training_framing_and_is_positive_controlled():
    """BUILD-PLAN U8. The old check sent the bare prefix as a user turn; a memorising adapter trained on
    system + "Note for the record." -> "<prefix> <secret>." could pass it. The new check probes that framing."""
    c = make_canaries(2)
    rows = canary_rows(c, "SYS", repeats=3)
    assert len(rows) == 6 and rows[0]["prompt"][1]["content"] == USER_TURN
    assert rows[0]["completion"][0]["content"].startswith(c[0]["prefix"])
    # the probes reproduce the training context exactly
    msgs, pre = probe_messages("SYS", "context", c[0])
    assert msgs == rows[0]["prompt"] and pre is None
    msgs, pre = probe_messages("SYS", "prefill", c[0])
    assert msgs == rows[0]["prompt"] and pre == c[0]["prefix"]
    # a silent generator passes; the leaky one is caught in both training-framed modes
    assert leak_check(lambda m, p: "nothing", c, "SYS")["pass"]
    pc = positive_control(c, "SYS")
    assert pc["detected"] and pc["leaked"] == 2 and not pc["pass"]
    # a generator that only leaks when the training context is given (the case the old check missed)
    def only_in_context(m, p):
        return f"{c[1]['prefix']} {c[1]['secret']}." if (p is None and m[-1]["content"] == USER_TURN) else "no"
    r = leak_check(only_in_context, c, "SYS")
    assert not r["pass"] and r["leaked_ids"] == [c[1]["id"]] and r["leaked_by_mode"][c[1]["id"]] == ["context"]
    assert leak_check(only_in_context, c, "SYS", modes=("bare",))["pass"], "the old bare-prefix mode alone misses it"
    # the leaky generator never answers a bare prefix with its secret unless pre-filled; prefill catches it
    assert "prefill" in leak_check(leaky_generator(c), c, "SYS")["leaked_by_mode"][c[1]["id"]]


def _write_synthetic_data(tmp_path, with_marker=True):
    data = tmp_path / "data"
    data.mkdir()
    train = [mkrow(i, f"2026-10-{i + 1:02d}", f"q{i}", i % 3) for i in range(20)]
    tr, va, can = make_sft.build(train, n_canaries=1)
    ingest.write_jsonl(data / "sft_train.jsonl", tr)
    ingest.write_jsonl(data / "sft_val.jsonl", va)
    ingest.write_jsonl(data / "test.jsonl", train[:3])
    (data / "canaries.json").write_text(json.dumps(can))
    if with_marker:
        (data / approval.SYNTHETIC_MARKER).write_text("synthetic")
    return data


def test_approval_is_bound_to_file_hashes(tmp_path):
    """BUILD-PLAN U10: an approval records the SHA-256 of the training files; a rebuilt file voids it."""
    data = _write_synthetic_data(tmp_path, with_marker=False)
    p = tmp_path / "local" / "review-gate-approval.json"
    ok, why = approval.check_approval(p, data)
    assert not ok and "no signed" in why
    doc = approval.write_approval(p, data, "the owner's words")
    assert set(doc["sha256"]) == set(approval.APPROVAL_FILES)
    assert approval.check_approval(p, data) == (True, "approved and hashes match")
    assert make_sft.approved(data)
    # the old path-only format is refused
    p.write_text(json.dumps({"approved": True, "corpus": "x"}))
    ok, why = approval.check_approval(p, data)
    assert not ok and "SHA-256" in why
    # a rebuilt training file voids a valid approval
    approval.write_approval(p, data, "again")
    with (data / "sft_train.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"prompt": [], "completion": [], "id": "x"}) + "\n")
    ok, why = approval.check_approval(p, data)
    assert not ok and "sft_train.jsonl changed" in why
    assert not make_sft.approved(data)


def test_amd_script_gates_real_and_synthetic_data(tmp_path):
    import train_lora_amd as t
    data = _write_synthetic_data(tmp_path, with_marker=False)
    assert t.main(["--data", str(data), "--dry-run"]) == 2, "must refuse without the owner's review-gate approval"
    assert t.main(["--data", str(data), "--dry-run", "--no-approval-check"]) == 2, "no marker: real data cannot skip the gate"
    (data / approval.SYNTHETIC_MARKER).write_text("synthetic")
    assert t.main(["--data", str(data), "--dry-run", "--no-approval-check"]) == 0
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "review-gate-approval.json").write_text(json.dumps({"approved": True}))
    assert t.main(["--data", str(data), "--dry-run"]) == 2, "an approval without hashes is refused"
    approval.write_approval(tmp_path / "local" / "review-gate-approval.json", data, "yes")
    assert t.main(["--data", str(data), "--dry-run"]) == 0
    rep = t.check(data)
    assert rep["ok"] and rep["canary_rows"] == 3 and rep["train_rows"] == 21


def test_amd_script_flags_resolve():
    import train_lora_amd as t
    import contextlib, io
    data = Path(__file__).parent / "nonexistent"
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        t.main(["--data", str(data), "--dry-run", "--qlora", "--precision", "fp16", "--batch", "1", "--grad-accum", "16", "--max-len", "1024"])
    cfg = json.loads(buf.getvalue())["config"]
    assert cfg["qlora"] and cfg["precision"] == "fp16" and cfg["batch"] == 1 and cfg["grad_accum"] == 16
    assert cfg["max_len"] == 1024 and cfg["grad_ckpt"] and cfg["optim"] == "paged_adamw_8bit"
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        t.main(["--data", str(data), "--dry-run"])
    cfg = json.loads(buf.getvalue())["config"]
    assert cfg["batch"] == 8 and cfg["grad_accum"] == 2 and cfg["precision"] == "auto" and not cfg["grad_ckpt"]


def test_synthetic_writer_marks_folder_and_realistic_lengths(tmp_path):
    out = tmp_path / "syn"
    s = synthetic.write(out, n=40, realistic=True, n_canaries=2)
    assert (out / approval.SYNTHETIC_MARKER).exists() and s["canaries"] == 2
    rows = synthetic.rows(200, realistic=True)
    lens = [len(r["question"]) + sum(len(o["label"]) + len(o["description"]) for o in r["options"]) for r in rows]
    assert 400 < sum(lens) / len(lens) < 2500 and max(lens) > 1500, "a long tail like the real view"
    assert all(r["options"][0]["label"].endswith("(Recommended)") for r in rows)
    short = synthetic.rows(5)
    assert all(len(r["question"]) < 80 for r in short)
