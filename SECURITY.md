# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's **Report a vulnerability** button on this
repository's Security tab (private vulnerability reporting). If that button is not shown, open an issue that says only
that you have a security report and would like a private contact, with no details.

Supported version: the latest release (1.0.x).

## What this project protects

The council is trained on one person's history, which is full of other people. The assets are, in order: the owner's
raw transcripts, the people who appear in them, the cleaned training view, the trained adapter (which could memorise
rows), and the owner's trust in the council's suggestions. The design rules are in
[docs/PRIVACY-PIPELINE.md](docs/PRIVACY-PIPELINE.md); this file maps them to code.

## OWASP Top 10 for LLM Applications (2025)

The only LLM call path is: benchmark rows or an agent's question → a prompt → a local model (Ollama, or the trained
adapter in `build/train/`) → one option number. Every row below names the control, where it lives, and what it does
**not** cover.

| Risk | Control | Where | Residual risk |
| --- | --- | --- | --- |
| **LLM01 Prompt injection** | Transcript and agent text is untrusted. Prompt v1 (the default) fences it inside `<question>` / `<past_decision>` tags, turns `<` and `>` in the data into inert guillemets so nothing can close the fence or open a fake `<system>` block, strips control and bidirectional-override characters, caps each field's length, and says in the system prompt that text inside the tags is data, never instructions. Tests plant a tag-spoofing injection and check the fence holds. | `council_eval/prompts.py`; `tests/test_v1.py` | Fencing lowers the odds of a steered answer; it cannot make a model immune. The impact is bounded by LLM05 and LLM06: the worst outcome is a wrong suggestion, which the owner sees beside the question. The frozen v0 prompt (kept only to reproduce published numbers) has no fence. |
| **LLM02 Sensitive information disclosure** | Rows only go to a model on this machine: the Ollama host must be `localhost` or a loopback IP (`COUNCIL_OLLAMA_HOST`), and a remote host is refused before any request. Before training, the scrubber redacts emails, national ID numbers, phone and card numbers, keys and URL queries, pseudonymises names with an HMAC under a local key, and drops rows about minors. `council info` never prints the owner's name. | `predictors.loopback_host`, `scrub.py`, `config.py` | The regex scrubber misses what it has no pattern for; that is why stage 5 (a human review) exists. A rented GPU for training is an explicit, approval-gated exception (README). |
| **LLM03 Supply chain** | The harness is pure standard library: no runtime dependencies. Training dependencies are an opt-in extra. The base model can be pinned to a Hugging Face commit with `--revision`; `trust_remote_code` is never passed; adapters are written by `save_model`, which uses safetensors by default. | `pyproject.toml`, `train/train_lora_amd.py` | `--revision` is optional and the training extra is unpinned. Pin both for a release-grade training run. |
| **LLM04 Data and model poisoning** | Nothing reaches weights without the owner's signed approval, bound to the SHA-256 of every training file; a rebuilt file voids it. The approval follows a review sheet of before-and-after samples. After training, a canary audit (with a positive control that must detect a deliberately leaky generator) discards any adapter that memorised a canary. | `approval.py`, `review_sheet.py`, `canary.py` | An agent can still word questions to nudge the owner, and the owner's answers are the training target; the review sheet is the control. |
| **LLM05 Improper output handling** | The model's reply is parsed into an in-range option index or nothing (`parse_choice`; JSON is parsed strictly). It is never executed, never rendered as HTML and never written back to the agent. | `prompts.parse_choice` | None known. |
| **LLM06 Excessive agency** | The model has no tools. `council ask` prints a suggestion beside the full question and never answers for the owner; the planned auto-answer mode keeps that rule (docs/PRIOR-ART.md). | `ask.py` | None while the council only suggests. |
| **LLM07 System prompt leakage** | The system prompt holds no secrets: only the owner's display name, which the owner sets. | `prompts.py` | None. |
| **LLM08 Vector and embedding weaknesses** | Retrieval (arm A2, `council ask --k`) is TF-IDF over the owner's own training rows only; retrieved rows are fenced like the question. | `predictors.TfidfIndex` | A poisoned past row could be retrieved as an example; see LLM04. |
| **LLM09 Misinformation** | A model is only deployed if it passes pre-registered gates, including a floor on the decisions where the owner overrode the agent, so an agent-imitator cannot pass. Until then `council ask` labels its pick a weak hint from an untrained base model. | `metrics.GATES`, `metrics.gates()` | Passing the gates on past decisions is not a guarantee on new ones. |
| **LLM10 Unbounded consumption** | Each request has a timeout, a reply-length cap (`num_predict`), a context cap, a prompt-size cap and a reply-size cap; retries are bounded at three. `council ask` caps input size, questions and options. | `predictors.ollama_chat`, `ask.py` | A slow local model can still take minutes over a full test split; that is the owner's own machine and choice. |

## Other surfaces

- **Retest server** (`build/retest/server.mjs`): binds `127.0.0.1` only, rejects any `Host` header that is not
  loopback (DNS rebinding), caps request bodies at 256 KB, validates every response, and serves the page with a
  Content-Security-Policy that allows no other origin (inline script is allowed, because the page is one file). The page builds the DOM from text nodes, never from HTML strings.
- **Secrets and data in git:** `.gitignore` and `build/.gitignore` exclude data, corpora, transcripts, results,
  adapters and weights; the local alias table, HMAC key and settings live in `build/local/`, which git ignores.
- **CI:** read-only `contents` permission, no secrets, checkout without persisted credentials.
