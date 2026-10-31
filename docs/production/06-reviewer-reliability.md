# 06 - Reviewer reliability (a measured finding)

## Symptom

Two live runs on "How to improve your sleep" both ended `needs_review` with a
reviewer score of exactly `0.0`, even though the articles were on topic, cited
real sources and passed 15-17 of the deterministic checks.

## Investigation

1. **Not a parsing bug.** Calling the model with `include_raw=True` showed valid
   JSON and `parsing_error: None`. The score was a real model output.
2. **Same article, same prompt, different answers.** Scoring one stored article
   repeatedly gave 0.75 / 0.65 (direct probe) and 0.0 / 0.0 (through
   `review_node`).
3. **Bisecting the prompt** (3 samples each, same article):

| Prompt variant | Scores |
|---|---|
| Original (sources list + "factual restraint") | 0.0, 0.0, 0.0 |
| Without the sources list | 0.0, 0.0, 0.75 |
| Without the "factual restraint" clause | 0.65, 0.0, 0.75 |
| Without the clause, with an explicit scale (0.7 = publishable) | 0.7, 0.7, 0.7 |

The "no invented claims" instruction made the 4B model treat the numbered
citations as fabrication. An explicit scale made it stable on this article.
I shipped that prompt.

4. **Does it still discriminate?** With the new prompt, 3 samples each:

| Article | Scores |
|---|---|
| Good sleep post | 0.7, 0.7, 0.7 |
| Entirely off-topic (volcanoes, stocks, pasta) | 0.0, 0.9, 0.0 |
| Gibberish | 0.0, 0.0, 0.7 |

The good article is now stable, but the reviewer gave an off-topic article 0.9
once and gibberish 0.7 once. At this size it is **not reliable enough to block
publishing**.

## Decision

- `llm_gate` (`COMEBLOG_LLM_GATE`) defaults to **false**: the reviewer score is
  recorded, shown on the page and used to pick the weakest section to rewrite,
  but it does not decide `published` vs `needs_review`.
- The deterministic checks are the gate. I added a per-section **relevance**
  check (share of the topic's key words present, 5-character stem match).
- Set `COMEBLOG_LLM_GATE=true` if you run a stronger reviewer model.

## What the relevance check does not catch

I ran it against both real articles. Every section passed (50-100%), including
the off-topic "Heart-Healthy Diet" section, because that section mentions sleep.
It catches text with no connection to the topic (the volcano/stocks/pasta
article fails in the unit test) but not a plausible adjacent topic. Catching
that needs either a stronger model or an embedding-based similarity check, which
needs a new dependency or an Ollama embedding model. Not done.

## Sample size

Each cell above is 3 samples on one article. These numbers show the reviewer is
noisy; they are not a benchmark.
