# AI Collaboration Note

## Did You Use AI?

Yes. Cursor (Grok) helped me read the challenge materials, inspect the CSV, and draft the first health-check script and writeups.

## How You Used It

I used it as a pairing partner: load the domain packet, list data issues, compute rollups, then turn that into a small CLI a teammate could run. I did not ask it to pick the track or the scope for me.

## One Prompt, Workflow, Or Moment That Helped

Asking it to flag every row that should not be trusted blindly surfaced the Aug 5 demo spike and duplicate together, and showed how much Lead summary would inflate if those rows stayed in the averages.

## One Thing You Verified Or Decided Yourself

I re-ran the script against the CSV and checked the Aug 7 Support queue row by hand (30 sessions, 17 completed, 8 accepted, 12 flagged, confidence 0.91, rating 2.1). From that contradiction I decided `median_confidence` is the least trustworthy metric, and that the prompt-change window is a no-call rather than a win.
