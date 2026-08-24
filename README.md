# SignalDesk Weekly Health Check

## Track Chosen

Track A: Fictional Domain Packet.

## What I Built

A single-command CLI (`python health_check.py`) that produces a weekly health briefing: five actionable recommendations, each backed by a small evidence table placed directly under it, plus data-quality flags (broken records) and context flags (valid records that change interpretation).

## Who It Is For

A product teammate deciding what is working, what looks suspicious, and whether to roll AI workflows out more broadly. It is not aimed at an analyst wanting a full BI dashboard.

## Data Or Source Used

Fictional export: `sample-data/product_usage_events.csv` (daily workflow summaries, 2026-08-01 to 2026-08-07). Definitions taken from `domain-packet.md`.

## Assumptions I Made

- `accepted_output / completed` is the best available proxy for usefulness; `completed` alone is not a quality measure.
- Demo traffic and near-duplicate export rows are dropped from health metrics, not averaged in.
- Only the Aug 7 policy-shock row is dropped from the post-prompt slice, not the whole day.
- `avg_minutes_saved` and `user_rating` are unweighted daily-row means and not treated as quality.
- Alert thresholds (10 pp drop, flag rate doubling) are initial operational values, not derived from one week of data.

## Data Issues Or Caveats I Noticed

**Data quality:**

- Near-duplicate rows that differ only in `notes`; exact-row `duplicated()` misses them.
- Team label `product` vs `Product`; `median_confidence` stored as the text `n/a`; missing ratings.

**Context:**

- Demo spike on 2026-08-05 (140 sessions, 0.95 confidence, 4.9 rating).
- Reply draft policy shock on 2026-08-07: 0.91 confidence but only 47% acceptance.
- Missing team/source combos on 2026-08-07.

## What I Would Do Next With More Time

Join prompt-version IDs and review-policy timestamps to the event grain; separate demo/test accounts at export time; add day-over-day alerts on accept and flag rates. I would not add more charts until those definitions are stable.

## Run

```bash
pip install -r requirements.txt
python health_check.py
```
