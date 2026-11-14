# The benchmark, in more detail

Status on 11 November 2026. Everything here comes from my own decisions. No model has been trained on them yet,
so this page says how untrained models did and what a trained one has to reach.

## What the model is asked

When a Claude Code agent stops and asks me to pick one of several options, the model is shown the same question
and the same options, and has to predict which one I pick.

There are 1,887 such decisions, made between 2 July and 10 November 2026. (Those sessions ran on Anthropic's
cloud models. Everything the council does with the transcripts afterwards runs on my laptop.) 1,510 are for a
model to learn from. The newest 375, from 3 to 10 November, are the test. The other 2 repeated an earlier
question, so they were left out. Testing on the newest decisions means the model has to predict what I do next,
not repeat what it has already seen.

## What counts as right

A prediction is right when it is the option I really chose. Two rules keep that honest.

- The agent's hint is hidden. Agents often mark one option as "recommended", and I usually take it. The benchmark
  removes that mark, so a model cannot score by spotting it.
- The options are shuffled. Agents tend to list their own pick first: before shuffling, always choosing the first
  option matched me about four times in five. After shuffling, the position of an option tells a model nothing.

## The decisions that matter most

Most of the time I take the agent's suggestion. Sometimes I do not, and those are the decisions a filter exists
for.

Take a rule that needs no model at all: always pick what the agent suggested. It looks good on paper, because I
agree with the agent most of the time. But it was wrong every single time I disagreed, because it can never
disagree. A model that only learned to agree with the agent would look just as good and would catch nothing.

So every model is scored twice: on all 375 test decisions, and on the ones where I went against the agent's
suggestion.

## What was found

No model has been trained yet. These are the starting points.

- Picking at random matches me about two times in five.
- The best untrained model is qwen3:4b, a small open model, run as it comes on a laptop graphics card. It picked
  what I picked about two times in three.
- On the decisions where I went against the agent, that same model got most of them wrong. It did worse there
  than picking at random.
- Showing the model four similar past decisions of mine before each question made it slightly worse overall. It
  did slightly better on the decisions where I went against the agent, but still worse than picking at random.

That is the gap training has to close.

## The pass mark for a trained Scrutiniser

The pass mark was fixed after the untrained runs and before any training, so it cannot be bent to fit a result.
A trained model has to clear all three parts.

- Overall, it has to match me about seven times in ten. That is clearly more often than the best untrained
  model, and the gain has to be bigger than luck could explain.
- On the decisions where I went against the agent, it has to do at least as well as the best untrained result.
  This is a low bar on purpose, and picking at random clears it. Its only job is to rule out a model that copies
  the agent, which gets none of those right. Picking at random fails the overall mark instead.
- It must not get noticeably worse on the decisions where I took the agent's suggestion. It must give a usable
  answer almost every time. And it must show no sign of having memorised its training data.

## Where the code is

The code is in [`build/council_eval/`](../build/council_eval/): the split by time, the locked test, the blind,
shuffled questions, the simple comparison rules, the scoring and the pass-mark checks. The two methods behind
this benchmark are described for reuse in [PRIOR-ART.md](PRIOR-ART.md).
