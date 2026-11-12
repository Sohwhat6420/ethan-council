# Changelog

All notable changes to Human LLM Council. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [1.0.0] - Unreleased

The first stable release of the toolkit: the Scrutiniser benchmark, the privacy pipeline, the evaluation harness, the
self-consistency retest and the training script, now installable and runnable from a fresh clone. **No trained model
ships with 1.0.0.** The Scrutiniser adapter on real data is still waiting for its owner's review-gate approval; when
one passes the pre-registered gates it will be a later release.

### Added

- **Install and CLI.** `pyproject.toml` (the harness is pure standard library; `[test]` and `[train]` extras) and a
  `council` command: `demo`, `info`, `ingest`, `split`, `eval`, `review`, `sft`, `synthetic`, `ask`, `train`,
  `version`. `python -m council_eval` does the same.
- **`council demo`.** The whole pipeline on synthetic transcripts in about a second: ingest with scrubbing,
  pseudonymisation and exclusions, the time split, blind and shuffled baselines with the oracle trap, the training
  view with canaries, the review sheet, the SHA-256-bound approval, and the gates.
- **`council ask`.** Shows an agent's question with the council's suggested option beside it, for the owner to accept
  or change. It never answers for the owner. Until an adapter passes the gates it uses an untrained local base model
  and says so.
- **Prompt v1** (the new default) with prompt-injection hardening; see Security.
- **Owner settings.** The owner's name and the prompt version come from `build/local/council.json` or
  `COUNCIL_OWNER` / `COUNCIL_PROMPT`, never from the code.
- **`COUNCIL_HOME`.** A regular (non-editable) install keeps its data in `~/.human-llm-council`, never in
  site-packages; a source checkout keeps using `build/`.
- **`view.json`** beside the training view records the prompt version and owner name. The training script renders
  its test prompts from it and refuses training rows whose system prompt disagrees.
- **`--revision`** on the training script, to pin the base model to a Hugging Face commit.
- **SECURITY.md** with an OWASP Top 10 for LLM Applications (2025) map, and this changelog.
- **Tests:** 32 new (53 Python tests in all, plus 14 for the retest tool), including the core flow end to end,
  prompt-injection and tag-spoofing cases, loopback enforcement and the CLI.
- **CI:** Python 3.10 to 3.13, Node 20 and 22, `council demo` on every run, and a job that installs from a clean
  checkout and runs the CLI from another folder.

### Changed

- **The default prompt is v1.** Results under v1 carry a `-v1` suffix in the arm name, so they are never paired with
  v0 files by accident. The published baselines were measured with v0: re-run the A1 baseline under v1 before gating
  an adapter trained on a v1 view, or build the view with `council sft --prompt v0`.
- `parse_choice` reads a JSON reply strictly: `{"choice": k}` with an integer from 1 to the number of options, else
  no answer. Bare-number replies are read as before.
- Neutral wording ("the owner") in code, reports and docs; the README no longer names the reference instance after
  its owner.
- The retest smoke test finds Playwright's Chromium on Linux and macOS as well as Windows (`--chrome` or
  `RETEST_CHROME` to override), runs without a sandbox when it is root on Linux, and never uses a proxy for its
  loopback page.
- Package version 0.1.0 → 1.0.0.

### Fixed

- `council review --approve` (`review_sheet --approve`) wrote the approval to the home folder's `local/` even when
  `--data` pointed elsewhere, where neither `make_sft` nor the training script looks. It now writes to
  `<data>/../local/review-gate-approval.json`, the path both checks read.

### Security

- Prompt v1 fences untrusted transcript and agent text, neutralises tag spoofing, strips control and bidirectional
  characters and caps field lengths (OWASP LLM01).
- The Ollama host must be loopback; a remote host is refused before any request (LLM02).
- Prompt-size, reply-size, timeout and reply-length caps on every model call (LLM10).
- The frozen v0 prompt is unchanged byte for byte, so the published numbers stay reproducible; a fingerprint test
  guards it. It has none of the v1 protections and is kept for reproduction only.

## [0.1.0] - 2026-11-11 (preview)

The public preview: the benchmark harness and its baselines on the reference instance's 1,887 decisions, the privacy
pipeline (stages 0 to 5 and 7), the laptop training test on synthetic data, the canary audit with a positive control,
the self-consistency retest tool, and the prior-art note and defensive publication.

[1.0.0]: https://github.com/Sohwhat6420/human-llm-council/compare/9cb69ab...HEAD
[0.1.0]: https://github.com/Sohwhat6420/human-llm-council/tree/9cb69ab
