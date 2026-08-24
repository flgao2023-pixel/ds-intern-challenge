#!/usr/bin/env python3
"""SignalDesk weekly health check.

Prints a one-page briefing a product teammate can paste into Slack, then
the tables behind it.

Stdlib only. Usage:
    python3 health_check.py
    python3 health_check.py path/to/product_usage_events.csv
"""

from __future__ import annotations

import csv
import math
import sys
import textwrap
from pathlib import Path
from statistics import median

DEFAULT_CSV = Path(__file__).resolve().parent / "sample-data" / "product_usage_events.csv"
PROMPT_START = "2026-08-04"
POLICY_NOTE = "review policy changed mid-day"
DEMO_NOTE = "traffic spike from demo account"
SMALL_SAMPLE_NOTE = "small sample"
PROMPT_NOTE = "new prompt version started"
NA_TOKENS = {"n/a", "na", "null"}

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
    if value.lower() in {"", *NA_TOKENS}:
        return None
    return float(value)


def round_half_up(value: float, ndigits: int = 2) -> float:
    scale = 10**ndigits
    return math.floor(value * scale + 0.5) / scale


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="") as handle:
        for raw in csv.DictReader(handle):
            conf_raw = (raw["median_confidence"] or "").strip()
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
                    "confidence_raw": conf_raw,
                    "rating": parse_float(raw["user_rating"]),
                    "notes": (raw.get("notes") or "").strip(),
                }
            )
    return rows


def drop_near_duplicates(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep the first row when date/team/workflow/source/counts match."""
    seen: set[tuple] = set()
    kept = []
    dropped = []
    for row in rows:
        key = (
            row["date"],
            row["team"],
            row["workflow"],
            row["source"],
            row["sessions"],
            row["completed"],
            row["accepted"],
            row["flagged"],
        )
        if key in seen:
            dropped.append(row)
            continue
        seen.add(key)
        kept.append(row)
    return kept, dropped


def mean_unweighted(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def median_present(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return float(median(present))


def summarize(rows: list[dict]) -> dict:
    sessions = sum(row["sessions"] or 0 for row in rows)
    completed = sum(row["completed"] or 0 for row in rows)
    accepted = sum(row["accepted"] or 0 for row in rows)
    flagged = sum(row["flagged"] or 0 for row in rows)
    return {
        "rows": len(rows),
        "sessions": sessions,
        "completed": completed,
        "accepted": accepted,
        "flagged": flagged,
        "completion": completed / sessions if sessions else None,
        "accept": accepted / completed if completed else None,
        "flag": flagged / completed if completed else None,
        "min_unw": mean_unweighted([row["minutes"] for row in rows]),
        "conf": median_present([row["confidence"] for row in rows]),
        "rtg_unw": mean_unweighted([row["rating"] for row in rows]),
    }


def pct(value: float | None) -> str:
    return f"{100 * value:.1f}%" if value is not None else "n/a"


def pp_delta(after: float | None, before: float | None) -> str:
    if after is None or before is None:
        return "n/a"
    return f"{100 * (after - before):+.1f} pp"


def wrap(text: str) -> str:
    return textwrap.fill(text, width=78, break_long_words=False, break_on_hyphens=False)


def fmt_num(value: float | None, digits: int) -> str:
    if value is None:
        return "n/a"
    return f"{round_half_up(value, digits):.{digits}f}"


def table_row(name: str, stats: dict) -> str:
    return (
        f"{name:<22} {stats['sessions']:>4} {stats['completed']:>4} "
        f"{stats['accepted']:>3} {stats['flagged']:>3} "
        f"{pct(stats['completion']):>8} {pct(stats['accept']):>7} {pct(stats['flag']):>7} "
        f"{fmt_num(stats['min_unw'], 2):>7} {fmt_num(stats['conf'], 2):>5} "
        f"{fmt_num(stats['rtg_unw'], 2):>7}"
    )


TABLE_HEADER = (
    f"{'name':<22} {'sess':>4} {'comp':>4} {'acc':>3} {'flg':>3} "
    f"{'complete':>8} {'accept':>7} {'flag':>7} {'min_unw':>7} {'conf':>5} {'rtg_unw':>7}"
)


def missing_expected(rows: list[dict]) -> list[str]:
    dates = sorted({row["date"] for row in rows})
    present = {(row["date"], row["team"], row["workflow"], row["source"]) for row in rows}
    missing = []
    for date in dates:
        for team, workflow, source in EXPECTED:
            if (date, team, workflow, source) not in present:
                missing.append(f"{date} {team}/{workflow}/{source}")
    return missing


def print_report(path: Path) -> None:
    raw = load_rows(path)
    deduped, dup_rows = drop_near_duplicates(raw)
    demo_rows = [row for row in deduped if row["notes"] == DEMO_NOTE]
    policy_rows = [row for row in deduped if row["notes"] == POLICY_NOTE]
    prompt_rows = [row for row in deduped if row["notes"] == PROMPT_NOTE]
    small_sample_rows = [row for row in raw if row["notes"] == SMALL_SAMPLE_NOTE]
    na_conf_rows = [row for row in raw if row["confidence_raw"].lower() in NA_TOKENS]
    missing_rating_rows = [row for row in raw if row["rating"] is None]
    casing_rows = [row for row in raw if row["team_raw"] != row["team"]]

    # Snapshot: drop near-duplicates and demo traffic; keep the policy-shock row.
    snapshot = [row for row in deduped if row["notes"] != DEMO_NOTE]
    # Prompt split: same, but also hold the policy-shock row out of "after".
    pre = [row for row in snapshot if row["date"] < PROMPT_START]
    post = [
        row
        for row in snapshot
        if row["date"] >= PROMPT_START and row["notes"] != POLICY_NOTE
    ]
    dates = sorted({row["date"] for row in raw})
    workflows = sorted({row["workflow"] for row in snapshot})
    sources = sorted({row["source"] for row in snapshot})
    by_workflow = {name: summarize([row for row in snapshot if row["workflow"] == name]) for name in workflows}
    by_source = {name: summarize([row for row in snapshot if row["source"] == name]) for name in sources}
    pre_wf = {name: summarize([row for row in pre if row["workflow"] == name]) for name in workflows}
    post_wf = {name: summarize([row for row in post if row["workflow"] == name]) for name in workflows}

    lead = by_workflow["Lead summary"]
    reply = by_workflow["Reply draft"]
    feedback = by_workflow["Feedback clustering"]
    post_days = sorted({row["date"] for row in post})
    demo = demo_rows[0]
    shock = policy_rows[0]
    shock_stats = summarize(policy_rows)
    missing = missing_expected(deduped)

    print()
    print(f"SignalDesk weekly health check | {dates[0]} to {dates[-1]}")
    print()
    print(
        wrap(
            f"Treat Lead summary as the only workflow that currently looks useful "
            f"enough to keep investing in. Cleaned accept rate is {pct(lead['accept'])} "
            f"on {lead['completed']} completed sessions, with a modest flag rate "
            f"({pct(lead['flag'])}). Reply draft completes often "
            f"({pct(reply['completion'])}) but users accept less "
            f"({pct(reply['accept'])}) and flag more ({pct(reply['flag'])}). "
            f"Feedback clustering is too small ({feedback['sessions']} sessions) "
            f"to call a winner."
        )
    )
    print(
        wrap(
            f"Do not treat the {PROMPT_START} prompt change as a company-wide win. "
            f"After dropping demo traffic and only the policy-shock row, "
            f"accept-rate change is Lead summary "
            f"{pp_delta(post_wf['Lead summary']['accept'], pre_wf['Lead summary']['accept'])}, "
            f"Reply draft {pp_delta(post_wf['Reply draft']['accept'], pre_wf['Reply draft']['accept'])}, "
            f"Feedback clustering {pp_delta(post_wf['Feedback clustering']['accept'], pre_wf['Feedback clustering']['accept'])}. "
            f"{len(post_days)} cleaned post-change day(s), plus a demo spike in the "
            f"same week, is not enough to roll the new prompt out more broadly."
        )
    )
    print(
        wrap(
            f"Investigate Reply draft before any broader rollout. {shock['date']} "
            f"({shock['source']}, {shock['notes']}) is the strongest warning: "
            f"{shock['completed']}/{shock['sessions']} completed, accepted "
            f"{shock['accepted']}, flagged {shock['flagged']} "
            f"(accept {pct(shock_stats['accept'])}, flag {pct(shock_stats['flag'])}). "
            f"Model confidence that day was {fmt_num(shock['confidence'], 2)}, which "
            f"did not track user acceptance. Find out whether the policy got "
            f"stricter, the new prompt got worse, or both."
        )
    )
    print(
        wrap(
            f"Trust median_confidence and avg_minutes_saved the least. "
            f"(Feedback clustering {fmt_num(feedback['min_unw'], 1)} min, "
            f"Lead summary {fmt_num(lead['min_unw'], 1)} min, "
            f"Reply draft {fmt_num(reply['min_unw'], 1)} min is a task difference, "
            f"not quality.) Lead summary unweighted minutes-saved moved "
            f"{post_wf['Lead summary']['min_unw'] - pre_wf['Lead summary']['min_unw']:+.2f} min "
            f"after the prompt change; ignore that as a win. User rating is thin "
            f"and got inflated by the demo spike ({fmt_num(demo['rating'], 1)})."
        )
    )
    print(
        wrap(
            "Weekly health check going forward: (a) drop near-duplicate export "
            "rows and any demo/test traffic, (b) report accept_rate and flag_rate "
            "by workflow — never a blended company average, (c) annotate prompt "
            "and policy changes on the same chart, (d) page a human if any "
            "workflow's accept_rate drops more than ~10 pp day-over-day or "
            "flag_rate doubles."
        )
    )
    print()
    print("DATA TRUST FLAGS")
    print(
        f"{len(na_conf_rows)} row(s) store median_confidence as the text "
        f"'n/a' (not a real missing value)."
    )
    print(f"{len(missing_rating_rows)} row(s) are missing user_rating.")
    if casing_rows:
        print("Team name casing is inconsistent ('product' vs title case). Normalized.")
    print(
        f"{len(dup_rows)} near-duplicate export row(s) dropped "
        f"(same date/team/workflow/source/counts)."
    )
    print(
        f"{len(demo_rows)} demo-account spike row excluded "
        f"({demo['date']} {demo['workflow']} / {demo['source']}: "
        f"{demo['sessions']} sessions)."
    )
    print(
        f"{len(policy_rows)} mid-day review-policy shock "
        f"({shock['date']} {shock['workflow']} / {shock['source']})."
    )
    print(
        f"New prompt version starts {PROMPT_START} "
        f"({len(prompt_rows)} annotated rows)."
    )
    if missing:
        print("Incomplete daily coverage: " + "; ".join(missing) + ".")
    print(
        f"{len(small_sample_rows)} row(s) are labeled small sample "
        f"(rates will swing hard)."
    )
    print()
    print("WORKFLOW SNAPSHOT (demo spike + duplicate removed)")
    print(TABLE_HEADER)
    for name in workflows:
        print(table_row(name, by_workflow[name]))
    print()
    print("BY SOURCE (same cleaned slice)")
    print(TABLE_HEADER)
    for name in sources:
        print(table_row(name, by_source[name]))
    print()
    print(
        "PROMPT CHANGE SPLIT | "
        f"pre {dates[0][5:]}..{sorted({row['date'] for row in pre})[-1][5:]} vs "
        f"post {PROMPT_START[5:]}..{dates[-1][5:]} "
        "(excludes only the policy-shock row)"
    )
    print("Before new prompt")
    print(TABLE_HEADER)
    for name in workflows:
        print(table_row(name, pre_wf[name]))
    print("After new prompt (cleaned)")
    print(TABLE_HEADER)
    for name in workflows:
        print(table_row(name, post_wf[name]))
    print()
    print("POLICY-SHOCK ROW (kept out of the post-prompt table)")
    print(
        f"{shock['date']} {shock['workflow']} / {shock['source']}: "
        f"sessions={shock['sessions']} completed={shock['completed']} "
        f"accepted={shock['accepted']}"
    )
    print(
        f"flagged={shock['flagged']} complete={pct(shock_stats['completion'])} "
        f"accept={pct(shock_stats['accept'])} flag={pct(shock_stats['flag'])} "
        f"confidence={fmt_num(shock['confidence'], 2)} "
        f"rating={fmt_num(shock['rating'], 1)}"
    )
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
