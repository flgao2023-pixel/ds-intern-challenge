#!/usr/bin/env python3
"""SignalDesk weekly health check.

One-page briefing for a product teammate: what looks usable, what is
untrustworthy, and what to investigate before a broader rollout.

Stdlib only. Usage:
    python3 health_check.py
    python3 health_check.py path/to/product_usage_events.csv
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parent / "sample-data" / "product_usage_events.csv"
PROMPT_START = "2026-08-04"
POLICY_NOTE = "review policy changed mid-day"
DEMO_NOTE = "traffic spike from demo account"
DUP_NOTE = "duplicate export row"

# Expected daily coverage. Used to surface missing exports, not to impute them.
EXPECTED = [
    ("Sales", "Lead summary", "email"),
    ("Sales", "Lead summary", "manual"),
    ("Support", "Reply draft", "queue"),
    ("Support", "Reply draft", "manual"),
    ("Product", "Feedback clustering", "csv upload"),
    ("Product", "Feedback clustering", "manual"),
]


def parse_int(value: str) -> int | None:
    value = (value or "").strip()
    return int(value) if value else None


def parse_float(value: str) -> float | None:
    value = (value or "").strip()
    if value.lower() in {"", "n/a", "na", "null"}:
        return None
    return float(value)


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="") as handle:
        for raw in csv.DictReader(handle):
            rows.append(
                {
                    "date": raw["date"].strip(),
                    "team_raw": raw["team"].strip(),
                    "team": raw["team"].strip().title(),
                    "workflow": raw["workflow"].strip(),
                    "source": raw["source"].strip(),
                    "sessions": parse_int(raw["sessions"]),
                    "completed": parse_int(raw["completed"]),
                    "accepted": parse_int(raw["accepted_output"]),
                    "flagged": parse_int(raw["flagged_for_review"]),
                    "minutes": parse_float(raw["avg_minutes_saved"]),
                    "confidence": parse_float(raw["median_confidence"]),
                    "rating": parse_float(raw["user_rating"]),
                    "notes": (raw.get("notes") or "").strip(),
                }
            )
    return rows


def flag_issues(rows: list[dict]) -> list[dict]:
    issues = []
    dates = sorted({row["date"] for row in rows})
    present = {
        (row["date"], row["team"], row["workflow"], row["source"])
        for row in rows
        if row["notes"] != DUP_NOTE
    }

    for row in rows:
        loc = f"{row['date']} {row['workflow']} / {row['source']}"
        if row["notes"] == DUP_NOTE:
            issues.append({"severity": "P0", "issue": "Duplicate export row — drop before any rollup", "where": loc})
        if row["notes"] == DEMO_NOTE:
            issues.append(
                {
                    "severity": "P0",
                    "issue": "Demo-account traffic in production metrics — exclude from health numbers",
                    "where": loc,
                }
            )
        if row["team_raw"] != row["team"]:
            issues.append({"severity": "P2", "issue": f"Team casing '{row['team_raw']}' vs '{row['team']}'", "where": loc})
        if row["confidence"] is None:
            issues.append({"severity": "P2", "issue": "median_confidence missing or stored as text", "where": loc})
        if row["rating"] is None:
            issues.append({"severity": "P2", "issue": "user_rating missing", "where": loc})
        if row["notes"] == POLICY_NOTE:
            issues.append(
                {
                    "severity": "P1",
                    "issue": "Review policy changed mid-day — do not average with earlier Support days",
                    "where": loc,
                }
            )
        if row["completed"] is not None and row["sessions"] is not None and row["completed"] > row["sessions"]:
            issues.append({"severity": "P0", "issue": "completed > sessions", "where": loc})
        if row["accepted"] is not None and row["completed"] is not None and row["accepted"] > row["completed"]:
            issues.append({"severity": "P0", "issue": "accepted_output > completed", "where": loc})

    for date in dates:
        for team, workflow, source in EXPECTED:
            if (date, team, workflow, source) not in present:
                issues.append(
                    {
                        "severity": "P1",
                        "issue": "Expected daily row missing from export",
                        "where": f"{date} {workflow} / {source}",
                    }
                )
    return issues


def analysis_rows(rows: list[dict]) -> list[dict]:
    """Drop the duplicate export and the demo spike. Keep the policy-change day
    so it can be inspected, but later summaries split it out."""
    return [row for row in rows if row["notes"] not in {DUP_NOTE, DEMO_NOTE}]


def summarize(rows: list[dict]) -> dict:
    sessions = sum(row["sessions"] or 0 for row in rows)
    completed = sum(row["completed"] or 0 for row in rows)
    accepted = sum(row["accepted"] or 0 for row in rows)
    flagged = sum(row["flagged"] or 0 for row in rows)
    minute_weight = sum((row["minutes"] or 0) * (row["completed"] or 0) for row in rows if row["minutes"] is not None)
    minute_n = sum(row["completed"] or 0 for row in rows if row["minutes"] is not None)
    rating_weight = sum((row["rating"] or 0) * (row["completed"] or 0) for row in rows if row["rating"] is not None)
    rating_n = sum(row["completed"] or 0 for row in rows if row["rating"] is not None)
    conf_weight = sum((row["confidence"] or 0) * (row["completed"] or 0) for row in rows if row["confidence"] is not None)
    conf_n = sum(row["completed"] or 0 for row in rows if row["confidence"] is not None)
    return {
        "rows": len(rows),
        "sessions": sessions,
        "completed": completed,
        "accepted": accepted,
        "flagged": flagged,
        "completion": completed / sessions if sessions else None,
        "accept": accepted / completed if completed else None,
        "flag": flagged / completed if completed else None,
        "minutes": minute_weight / minute_n if minute_n else None,
        "hours": minute_weight / 60 if minute_n else None,
        "rating": rating_weight / rating_n if rating_n else None,
        "confidence": conf_weight / conf_n if conf_n else None,
    }


def pct(value: float | None) -> str:
    return f"{100 * value:5.1f}%" if value is not None else "   n/a"


def num(value: float | None, digits: int = 1) -> str:
    return f"{value:.{digits}f}" if value is not None else "n/a"


def line(label: str, stats: dict) -> str:
    return (
        f"{label:<36} "
        f"sess={stats['sessions']:>4}  "
        f"comp={pct(stats['completion'])}  "
        f"accept={pct(stats['accept'])}  "
        f"flag={pct(stats['flag'])}  "
        f"min/done={num(stats['minutes'])}  "
        f"hrs~{num(stats['hours'])}  "
        f"rating={num(stats['rating'], 2)}"
    )


def divider(title: str | None = None) -> str:
    bar = "-" * 88
    if not title:
        return bar
    return f"-- {title} " + "-" * max(0, 84 - len(title))


def print_report(path: Path) -> None:
    raw = load_rows(path)
    issues = flag_issues(raw)
    clean = analysis_rows(raw)
    comparable = [row for row in clean if row["notes"] != POLICY_NOTE]
    naive = [row for row in raw if row["notes"] != DUP_NOTE]
    dates = sorted({row["date"] for row in raw})
    workflows = ["Lead summary", "Reply draft", "Feedback clustering"]

    before = [row for row in comparable if row["date"] < PROMPT_START]
    after_stable = [
        row
        for row in comparable
        if PROMPT_START <= row["date"] <= "2026-08-06"
    ]
    support_pre = [
        row
        for row in clean
        if row["workflow"] == "Reply draft" and row["source"] == "queue" and row["notes"] != POLICY_NOTE
    ]
    support_policy = [row for row in clean if row["notes"] == POLICY_NOTE]
    lead_naive = summarize([row for row in naive if row["workflow"] == "Lead summary"])
    lead_clean = summarize([row for row in clean if row["workflow"] == "Lead summary"])

    print()
    print("SIGNALDESK WEEKLY HEALTH CHECK")
    print(f"Source: {path}")
    print(
        f"Window: {dates[0]} to {dates[-1]}  |  raw rows={len(raw)}  |  "
        f"cleaned={len(clean)}  |  comparable (no policy-change day)={len(comparable)}"
    )
    print("Audience: product teammate deciding whether to roll these workflows out more broadly")
    print()
    print(divider("HEADLINE"))
    print()
    print("Lead summary is the only workflow that looks steadily useful this week.")
    print("Do not treat this export as rollout-ready. Demo traffic would have inflated")
    print("Lead summary, and Support's Aug 7 review-policy change is a break in the series.")
    print("The Aug 4 prompt change does not show a clear lift once junk rows are removed.")
    print()
    print(divider("WHAT LOOKS SUSPICIOUS"))
    print()
    print(f"{'SEV':<4} {'ISSUE':<68} WHERE")
    for issue in issues:
        print(f"{issue['severity']:<4} {issue['issue']:<68} {issue['where']}")
    print()
    print("If the demo spike is left in, Lead summary looks better than it is:")
    print(
        f"  accept {pct(lead_naive['accept'])} vs cleaned {pct(lead_clean['accept'])}   "
        f"hours-saved {num(lead_naive['hours'])} vs {num(lead_clean['hours'])}   "
        f"rating {num(lead_naive['rating'], 2)} vs {num(lead_clean['rating'], 2)}"
    )
    print()
    print(divider("WORKFLOW COMPARISON  (demo + duplicate + Aug 7 policy day excluded)"))
    print()
    print("Accept rate = accepted_output / completed. That is a usefulness proxy, not quality.")
    print("Minutes saved are estimates. Do not average these workflows together.")
    print()
    for workflow in workflows:
        print(line(workflow, summarize([row for row in comparable if row["workflow"] == workflow])))
    print()
    print("By source (same cleaning):")
    for workflow in workflows:
        sources = sorted({row["source"] for row in comparable if row["workflow"] == workflow})
        for source in sources:
            stats = summarize(
                [row for row in comparable if row["workflow"] == workflow and row["source"] == source]
            )
            print(line(f"  {workflow} / {source}", stats))
    print()
    print("Reading:")
    print("  - Lead summary / email: highest accept, lowest flags, stable minutes. Best current bet.")
    print("  - Reply draft: fine until Aug 7. Volume is real; the policy-change day is not.")
    print("  - Feedback clustering: most minutes per completion, but small n, weakest accept,")
    print("    and completion drifted down as volume grew. Directional only.")
    print()
    print(divider("DAILY ACCEPT RATE  (cleaned)"))
    print()
    header = f"{'date':<12}" + "".join(f"{name:>22}" for name in workflows)
    print(header)
    by_day = defaultdict(list)
    for row in clean:
        by_day[row["date"]].append(row)
    for date in dates:
        cells = [f"{date:<12}"]
        for workflow in workflows:
            stats = summarize([row for row in by_day[date] if row["workflow"] == workflow])
            cells.append(f"{pct(stats['accept']):>22}")
        print("".join(cells))
    print()
    print("Note: 2026-08-05 Lead summary is manual-only. The email row that day is the demo spike.")
    print()
    print(divider("AUG 4 PROMPT CHANGE  (Aug 1-3 vs Aug 4-6, cleaned; Aug 7 held out)"))
    print()
    print(f"{'workflow':<24} {'accept before':>14} {'accept after':>14} {'flag before':>14} {'flag after':>14}")
    for workflow in workflows:
        b = summarize([row for row in before if row["workflow"] == workflow])
        a = summarize([row for row in after_stable if row["workflow"] == workflow])
        print(
            f"{workflow:<24} {pct(b['accept']):>14} {pct(a['accept']):>14} "
            f"{pct(b['flag']):>14} {pct(a['flag']):>14}"
        )
    print()
    print("Call: no clear win. Accept is flat. Reply draft flags ticked up. Hold the prompt")
    print("judgment until there is a full week without demo junk or a mid-day policy change.")
    print()
    print(divider("SUPPORT REVIEW POLICY  (queue only)"))
    print()
    pre = summarize(support_pre)
    day = summarize(support_policy)
    print(line("queue before Aug 7", pre))
    print(line("queue on Aug 7", day))
    print()
    print(
        f"Same day, model confidence went {num(pre['confidence'], 2)} -> {num(day['confidence'], 2)} "
        f"while user rating went {num(pre['rating'], 2)} -> {num(day['rating'], 2)}."
    )
    print("That is why median_confidence is the metric I would trust least.")
    print()
    print(divider("WHAT TO DO NEXT"))
    print()
    print("1. Filter demo / test accounts out of the production export. Until then, weekly")
    print("   numbers can be moved by a single fake-busy day.")
    print("2. Do not roll the new Support review policy further until someone reads a sample")
    print("   of the Aug 7 flagged replies. Flags, accept, minutes, and rating all broke;")
    print("   confidence did not. We do not yet know if output got worse or review got stricter.")
    print("3. Repeat this check weekly with four numbers per workflow, never blended:")
    print("   sessions, completion rate, accept rate, flag rate. Drop known-junk rows first.")
    print("   Skip confidence. Treat minutes saved and ratings as supporting context only.")
    print()
    print(divider())
    print()


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    if not path.exists():
        print(f"CSV not found: {path}", file=sys.stderr)
        return 1
    print_report(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
