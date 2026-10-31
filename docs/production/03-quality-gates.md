# 03 - Quality gates

Baseline: the only gate was the evaluator model's own `passed` flag, and the
documented 0.7 threshold was never enforced.

## Two layers

1. **Deterministic checks** (`quality.py`, no model, instant, testable)
2. **Independent LLM reviewer** (`qwen3:4b`, reasoning off) returning a 0-1
   score, feedback and the single weakest section

An article passes only if **every blocking check passes AND the reviewer score is
>= `COMEBLOG_PASS_THRESHOLD`** (or the reviewer is unavailable, in which case the
deterministic layer decides alone).

| Check | Scope | Blocking |
|---|---|---|
| `length:<section>` within 0.6x-1.8x of the target word range | per section | yes |
| `clean:<section>` no "Here is..." / "As an AI" preamble | per section | yes |
| `coverage:<section>` planned key points actually appear | per section | no |
| `unique_headings` | article | yes |
| `no_repetition` >= 90% of long sentences unique | article | yes |
| `valid_citations` every `[n]` resolves to a real source | article | yes |
| `cites_sources` at least 2 distinct sources cited | article | no |
| `has_excerpt` 40-220 chars, `has_takeaways` >= 3 | article | no |

## Targeted rewrites

Failing per-section checks and the reviewer's "weakest section" become the
rewrite list. Only those sections are regenerated (with the reviewer feedback in
the prompt); passing sections are kept. Baseline behaviour was to regenerate the
entire draft.

## Honest publishing

After `COMEBLOG_MAX_ATTEMPTS` the pipeline stops. If the bar is still not met the
post is saved with `status: needs_review`, shown with a visible badge on the
card and article, and counted in `/posts` stats. It is never silently published
as good.

## Observed on a real model

In the first live run the reviewer flagged a "Heart-Healthy Diet" section as the
weak part of a sleep article and triggered a one-section rewrite, which is the
intended behaviour. The planner (a 3B model) producing an off-topic section is a
known limit of small local models; the reviewer loop is what contains it.

## Tests added

5 quality tests + 8 pipeline tests (full publish, targeted rewrite, attempt cap
to `needs_review`, reviewer outage, schema-break fallback, event delivery,
percentage-score normalisation).
