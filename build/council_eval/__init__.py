"""Human LLM Council: the Scrutiniser benchmark, privacy pipeline and evaluation harness.

Local only. Reads Claude Code transcripts on this machine, turns the owner's AskUserQuestion answers into a
multiple-choice benchmark of their own rulings, scrubs it, splits it by time, and scores predictor arms (baselines,
a local Ollama model, retrieval, and a trained LoRA adapter) against pre-registered gates.
Design: ../../README.md and ../../docs/. BUILD-PLAN and Lane references in comments point at private research notes.
"""
__version__ = "1.0.0"
