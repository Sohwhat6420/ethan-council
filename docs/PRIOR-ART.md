# Prior art and defensive publication

**Published: 11 November 2026**, by Ethan Soh, in this repository. The commit that adds this file is the
dated public record.

This note does two things. It names the work this project builds on, so nobody has to guess what is new
and what is borrowed. And it describes two methods in enough detail for anyone to reproduce them, so they
are prior art from this date and free for anyone to use. Nothing here is patented, and no patent has been
applied for. This is a technical note by someone who is not a patent attorney, not legal advice.

## What is not new

A model of one person, trained on that person's history, that answers for them, has been done before:

- **Park et al. 2024**, *LLM Agents Grounded in Self-Reports Enable General-Purpose Simulation of
  Individuals* ([arXiv:2411.10109](https://arxiv.org/abs/2411.10109)): agents of 1,052 people predict
  their held-out survey answers, measured against each person's own test-retest consistency. The
  benchmark's planned retest ceiling follows this precedent.
- **Wu et al. 2025**, *Towards Automating Data Access Permissions in AI Agents*
  ([arXiv:2511.17959](https://arxiv.org/abs/2511.17959), IEEE S&P 2026): a model learns a user's
  permission decisions and makes them for the user. The closest academic analogue to answering an
  agent's approval questions on the user's behalf.
- **Microsoft's 2018 patent family**, *Expediting interaction with a digital assistant by predicting user
  responses*: US 10,878,805 B2, US 11,823,661 B2, US 12,469,485 B2 and EP 3 891 596 B1. Their claims cover
  a model that predicts the user's reply to an assistant's question and, when confident, supplies it
  without showing the question.
- **Meta, US 12,513,102 B2**, *Simulation of a user of a social networking system using a language model*.
- Per-user adapters and routing (OPPU, Profile-to-PEFT, per-user LoRA work), local personal models
  (Second Me), and memorisation canaries (Carlini et al. 2019, *The Secret Sharer*).

**Design choice that follows from the Microsoft family:** the council's planned auto-answer mode always
shows the agent's question, with the council's pick preselected for the owner to accept or change. It never
answers silently.

## What may be new, published here so it stays open

To my knowledge no public benchmark scores a user-proxy on the cases where the user overrode the agent.
Absence from a search is not proof of absence; if you know of earlier work, please open an issue and it
will be cited.

### Method 1: recommendation-blind training and testing (F3)

The setting: an AI agent asks its user a multiple-choice question and usually marks one option as its own
recommendation. A model of the user is trained and tested to predict which option the user picks.

The problem: users follow the agent's recommendation most of the time (81.7% in this project's data), and
the recommended option is usually listed first. A predictor that reads the marker, or the position, scores
well without modelling the user at all: on this project's unshuffled rows, "always answer option 1" scores
79.2%.

The method:

1. **Hide the recommendation.** Remove every recommendation cue from the question and each option before
   the model sees it: the "(Recommended)" label, "Recommended:" prefixes and suffixes, bracketed forms, and
   any residual stem ("I recommend", "recommendation"). Rows where a cue survives stripping are tagged and
   scored separately, so a leak is visible in the numbers.
2. **Shuffle the options** with a permutation seeded from a hash of the row id, so the order is
   reproducible but carries no information; map the prediction back through the inverse permutation.
3. **Apply both in training and in testing.** The training view uses the same blind, shuffled prompt as
   the test, so the model cannot learn the cue during training either.
4. **Split by time**, never at random: train on older decisions, test on the newest, with the test ids
   frozen by SHA-256 before any arm is scored.
5. **Report the oracle.** An arm that simply picks the agent's recommendation (using metadata the blind
   model cannot see) is scored alongside, so readers see how much of any accuracy is mere agreement with
   the agent.

### Method 2: the override-accuracy deployment gate (F4)

Overall accuracy can be passed by imitating the agent: in this project an oracle that always picks the
agent's recommendation scores 71.5% overall and 0% on the cases where the user disagreed. So a candidate
model of the user is only deployed if it clears, together:

1. an overall accuracy floor (here: the best untrained baseline plus 5 points, 70.6%), with a paired
   significance test against that baseline (exact McNemar, p < 0.05);
2. **a floor on override accuracy**: accuracy on the subset of test cases where the user chose something
   other than the agent's recommendation (here: at least 24.5%, the best baseline's measured value);
3. no material drop in follow accuracy (the subset where the user took the recommendation), no more than 1%
   unparsed replies, and zero canary leaks.

The gates are fixed before training (pre-registered) and implemented in
[`build/council_eval/metrics.py`](../build/council_eval/metrics.py) (`GATES`, `gates()`). In the test suite an
imitator scoring 71.5% overall and 0% on overrides fails, and so did a laptop test adapter trained on
synthetic rows that always copy the recommendation (87.0% overall, 0% on overrides).

## Licence

Code in this repository is Apache-2.0. The licence includes a patent grant from contributors for their
contributions; it grants nothing under anyone else's patents.
