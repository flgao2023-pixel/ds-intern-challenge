# AI Collaboration Note

## Did You Use AI?

Yes. Three models in three roles: one to draft, one to review, one to score.

## How You Used It

First, I used AI to decide what kind of report was worth shipping. Cursor with Grok 4.6 digested the challenge docs, inspected the messy CSV, helped pick a finishable scope (one weekly briefing, not a dashboard), and produced the first version of `health_check.py`, the README, and this note. A second Cursor model then acted as a strict reviewer of the code and both markdown files. I pasted the CLI output into ChatGPT for an outside review and score. I arbitrated rather than applying feedback wholesale: I kept changes that made the briefing more useful (evidence tables under the conclusions they support, softer claim wording, flags split into data-quality vs context) and rejected suggestions that conflicted with the data or the stated methodology, like citing sparse `user_rating` as evidence or replacing computed "typical" values with hand-estimated ranges.

Second, I used AI to check that the results were correct. Before locking the numbers I had the published rates recomputed from the raw CSV with a second script, without calling the summarizer, to confirm they matched. The same check confirmed the ingest steps: the Aug 5 near-duplicate is dropped, the literal n/a confidence is coerced to missing, mixed team casing is normalized, and the demo row is excluded from the rates.

## One Prompt, Workflow, Or Moment That Helped

Asking the model to turn a vague teammate ask ("what is working, what looks suspicious") into one artifact forced a scope cut: a CLI health check with explicit trust flags, instead of a multi-page notebook or Streamlit app.

## One Thing You Verified Or Decided Yourself

During the review loop, the reviewer model claimed accept rates were already "trending up" before the Aug 4 prompt change, while quoting numbers that actually fell (82.9% to 80%). I caught the contradiction and had the daily accept rates recomputed from the cleaned data: all three workflows were drifting slightly **down** pre-change and ticked up on the change day itself. The conclusion ("evidence inconclusive, do not roll out") survived, but now for reasons that match the data.
