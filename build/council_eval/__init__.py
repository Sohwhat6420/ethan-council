"""HUMAN LLM COUNCIL, Scrutiniser benchmark and evaluation harness (BUILD step 1, 10 Nov 2026).

Local only. Reads Claude Code transcripts on this machine, turns his AskUserQuestion answers into a
multiple-choice benchmark of his own rulings, scrubs it, splits it by time, and scores predictor arms
(baselines, a local Ollama model, retrieval, and later the LoRA trained on the AMD credit).
Design: ../../README.md and ../../docs/. BUILD-PLAN and Lane references in comments point at private research notes.
"""
__version__ = "0.1.0"
