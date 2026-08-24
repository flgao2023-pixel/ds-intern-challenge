# SignalDesk Weekly Health Check

## Track Chosen

Track A: Fictional Domain Packet

## What I Built

A stdlib Python CLI that prints a pasteable weekly briefing, then the tables behind it: data-trust flags, a cleaned workflow snapshot, a by-source cut, a prompt-change split, and the Aug 7 policy-shock row.

```bash
python3 health_check.py
```

## Who It Is For

The SignalDesk product teammate deciding what is working, what looks suspicious, and whether to roll these workflows out more broadly.

## Data Or Source Used

`sample-data/product_usage_events.csv` — fictional daily workflow summaries, 2026-08-01 to 2026-08-07. Domain terms are in `domain-packet.md`.

## Assumptions I Made

- `accepted_output / completed` is the best available usefulness proxy, not a quality label.
- `sessions` are workflow runs, not unique users.
- Workflows should not be averaged together.
- The Aug 5 demo-account spike (and its duplicate export) should be excluded from metrics.
- Model `median_confidence` is not correctness.

## Data Issues Or Caveats I Noticed

Duplicate export row; demo traffic mixed into production metrics; `product` vs `Product`; `n/a` stored as confidence; one missing rating; two missing Aug 7 source rows; Support review-policy change that makes Aug 7 incomparable.

## What I Would Do Next With More Time

Filter demo accounts at the source; sample Aug 7 flagged Support replies; wait for one clean week before judging the new prompt.
