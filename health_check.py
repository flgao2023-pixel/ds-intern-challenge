#!/usr/bin/env python3
"""SignalDesk weekly health check.

One job: help a product teammate decide what is working, what looks
untrustworthy, and what to investigate before a broader rollout.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

DEFAULT_DATA = Path(__file__).parent / "sample-data" / "product_usage_events.csv"

# Fallback if notes do not name a start date.
PROMPT_CHANGE_DATE = pd.Timestamp("2026-08-04")

COUNT_COLS = [
    "sessions",
    "completed",
    "accepted_output",
    "flagged_for_review",
    "avg_minutes_saved",
    "user_rating",
]


def load_raw(path: Path) -> pd.DataFrame:
    # Keep literal "n/a" so we can flag it. Default read_csv would swallow it.
    df = pd.read_csv(path, keep_default_na=False, na_values=[""])
    df["date"] = pd.to_datetime(df["date"])
    return df


def prompt_change_date(df: pd.DataFrame) -> pd.Timestamp:
    mask = df["notes"].astype(str).str.contains("new prompt version", case=False, na=False)
    if mask.any():
        return pd.Timestamp(df.loc[mask, "date"].min())
    return PROMPT_CHANGE_DATE


def post_change_slice(df: pd.DataFrame, change_date: pd.Timestamp) -> pd.DataFrame:
    """Rows on/after the prompt change, minus only the policy-shock row."""
    return df[(df["date"] >= change_date) & ~df["policy_shock"]].copy()


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Normalize messy fields.

    Returns (cleaned_frame, quality_flags, context_flags). Quality flags are
    broken records; context flags are valid records that change how the
    numbers should be read (policy change, demo traffic, small samples).
    """
    quality: list[str] = []
    context: list[str] = []
    out = df.copy()

    conf_raw = out["median_confidence"].astype(str).str.strip()
    n_na_text = int(conf_raw.str.lower().isin({"n/a", "na", "none"}).sum())
    if n_na_text:
        quality.append(
            f"{n_na_text} row(s) store median_confidence as the text 'n/a' "
            "(not a real missing value). Coerced to missing; the row is "
            "kept and confidence medians ignore it."
        )
    out["median_confidence"] = pd.to_numeric(out["median_confidence"], errors="coerce")
    for col in COUNT_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    missing_rating = int(out["user_rating"].isna().sum())
    if missing_rating:
        quality.append(
            f"{missing_rating} row(s) are missing user_rating. Kept; "
            "rating means use available rows only."
        )

    mixed_case = sorted(
        {
            t
            for t in out["team"].unique()
            if t != t.title() and t.title() in set(out["team"])
        }
    )
    if mixed_case:
        quality.append(
            f"Team name casing is inconsistent ({', '.join(repr(x) for x in mixed_case)} "
            "vs title case). Normalized to title case."
        )
    out["team"] = out["team"].str.title()

    # Export "duplicates" may differ only in the notes field.
    key_cols = ["date", "team", "workflow", "source", *COUNT_COLS]
    near_dup = out.duplicated(subset=key_cols, keep="first")
    n_near = int(near_dup.sum())
    if n_near:
        quality.append(
            f"{n_near} near-duplicate export row(s) dropped (same date / team / "
            "workflow / source / counts, different notes). Exact-row "
            "duplicated() would have missed these."
        )
    out = out.loc[~near_dup].copy()

    demo_mask = out["notes"].str.contains("demo account", case=False, na=False)
    n_demo = int(demo_mask.sum())
    if n_demo:
        demo = out.loc[demo_mask].iloc[0]
        context.append(
            f"{n_demo} demo-account spike row excluded from health metrics "
            f"({demo['date'].date()} {demo['workflow']} / {demo['source']}: "
            f"{int(demo['sessions'])} sessions, confidence {demo['median_confidence']}, "
            f"rating {demo['user_rating']})."
        )
    out["exclude_from_metrics"] = demo_mask

    policy_mask = out["notes"].str.contains("review policy changed", case=False, na=False)
    n_policy = int(policy_mask.sum())
    if n_policy:
        row = out.loc[policy_mask].iloc[0]
        context.append(
            f"{n_policy} mid-day review-policy shock "
            f"({row['date'].date()} {row['workflow']} / {row['source']}: "
            f"accept {int(row['accepted_output'])}/{int(row['completed'])} completed, "
            f"{int(row['flagged_for_review'])} flagged). Keep visible, do not treat as "
            "a normal quality day."
        )
    out["policy_shock"] = policy_mask

    change_date = prompt_change_date(out)
    prompt_mask = out["notes"].str.contains("new prompt version", case=False, na=False)
    if prompt_mask.any():
        context.append(
            f"New prompt version starts {change_date.date()} "
            f"({int(prompt_mask.sum())} annotated rows). Used as the "
            "pre/post split date in recommendation 2."
        )

    expected = (
        out.groupby(["team", "workflow", "source"], dropna=False)
        .size()
        .index
    )
    missing_days: list[str] = []
    for d in sorted(out["date"].unique()):
        have = set(
            map(
                tuple,
                out.loc[out["date"] == d, ["team", "workflow", "source"]].to_numpy(),
            )
        )
        for combo in expected:
            if combo not in have:
                missing_days.append(f"{pd.Timestamp(d).date()} {' / '.join(map(str, combo))}")
    if missing_days:
        context.append(
            "Incomplete daily coverage (combo present in the export overall, "
            f"missing on that day): {'; '.join(missing_days)}. Nothing "
            "dropped; day totals for those dates undercount."
        )

    small = out["notes"].str.contains("small sample", case=False, na=False)
    if small.any():
        context.append(
            f"{int(small.sum())} row(s) are labeled small sample; rates may "
            "be unstable. Kept in aggregates for completeness, but not used "
            "as standalone evidence for workflow rankings."
        )

    return out, quality, context


def add_rates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["completion_rate"] = out["completed"] / out["sessions"]
    out["accept_rate"] = out["accepted_output"] / out["completed"]
    out["flag_rate"] = out["flagged_for_review"] / out["completed"]
    return out


def weighted_rate(df: pd.DataFrame, num: str, den: str) -> float:
    d = df[den].sum()
    if d == 0:
        return float("nan")
    return float(df[num].sum() / d)


def summarize(df: pd.DataFrame, group: str) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(group, sort=True):
        rows.append(
            {
                group: key,
                "sessions": int(g["sessions"].sum()),
                "completed": int(g["completed"].sum()),
                "accepted": int(g["accepted_output"].sum()),
                "flagged": int(g["flagged_for_review"].sum()),
                "completion_rate": weighted_rate(g, "completed", "sessions"),
                "accept_rate": weighted_rate(g, "accepted_output", "completed"),
                "flag_rate": weighted_rate(g, "flagged_for_review", "completed"),
                # Unweighted mean of daily rows — not a volume-weighted total.
                "avg_minutes_saved": g["avg_minutes_saved"].mean(),
                "median_confidence": g["median_confidence"].median(),
                "user_rating": g["user_rating"].mean(),
                "days": int(g["date"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def fmt_pct(x: float) -> str:
    if pd.isna(x):
        return "  n/a"
    return f"{100 * x:5.1f}%"


def fmt_num(x: float, digits: int = 2) -> str:
    if pd.isna(x):
        return "n/a"
    return f"{x:.{digits}f}"


def block_table(headers: list[str], rows: list[list[str]]) -> str:
    """Small indented table meant to sit under the recommendation it supports."""
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    def line(cells: list[str]) -> str:
        parts = [
            c.ljust(w) if i == 0 else c.rjust(w)
            for i, (c, w) in enumerate(zip(cells, widths))
        ]
        return ("   " + "  ".join(parts)).rstrip()

    rule = "   " + "-" * (sum(widths) + 2 * (len(widths) - 1))
    return "\n".join([line(headers), rule, *[line(r) for r in rows]])


def period_label(df: pd.DataFrame) -> str:
    if df.empty:
        return "n/a"
    return f"{df['date'].min().date()} to {df['date'].max().date()}"


def _row(summary: pd.DataFrame, workflow: str):
    hit = summary.loc[summary["workflow"] == workflow]
    if hit.empty:
        return None
    return hit.iloc[0]


def build_recommendation(clean_df: pd.DataFrame) -> list[str]:
    usable = add_rates(clean_df.loc[~clean_df["exclude_from_metrics"]].copy())
    by_wf = summarize(usable, "workflow")
    change_date = prompt_change_date(clean_df)
    pre = usable[usable["date"] < change_date]
    post = post_change_slice(usable, change_date)
    pre_wf = summarize(pre, "workflow").set_index("workflow")
    post_wf = summarize(post, "workflow").set_index("workflow")

    lead = _row(by_wf, "Lead summary")
    reply = _row(by_wf, "Reply draft")
    cluster = _row(by_wf, "Feedback clustering")

    wf_rows = [
        [
            str(r["workflow"]),
            str(int(r["completed"])),
            fmt_pct(r["accept_rate"]).strip(),
            fmt_pct(r["flag_rate"]).strip(),
        ]
        for _, r in by_wf.sort_values("accept_rate", ascending=False).iterrows()
    ]
    wf_table = block_table(["workflow", "completed", "accept", "flag"], wf_rows)

    no_shock = summarize(usable.loc[~usable["policy_shock"]], "workflow")
    reply_holdout = _row(no_shock, "Reply draft")

    lines = []
    if lead is not None and reply is not None and cluster is not None:
        holdout_note = ""
        if reply_holdout is not None:
            holdout_note = (
                "   Holding out the Aug 7 policy-shock row does not change "
                "the ranking: Reply draft would be "
                f"{fmt_pct(reply_holdout['accept_rate']).strip()} accept on "
                f"{int(reply_holdout['completed'])} completed, still below "
                f"Lead summary at {fmt_pct(lead['accept_rate']).strip()}.\n\n"
            )
        lines.append(
            "1. Continue investing in Lead summary. It has the strongest "
            "evidence of product value: the largest cleaned sample "
            f"({int(lead['completed'])} completed sessions) with the best "
            f"accept/flag balance ({fmt_pct(lead['accept_rate']).strip()} vs "
            f"{fmt_pct(lead['flag_rate']).strip()}).\n\n"
            f"{wf_table}\n\n"
            f"{holdout_note}"
            "   Feedback clustering shows weaker numbers, but its smaller "
            "sample makes the result less conclusive; we cannot yet "
            "distinguish a genuinely weaker workflow from normal variance."
        )
    else:
        lines.append(
            "1. Invest in the workflow with the highest accept rate and a "
            "modest flag rate; do not blend workflows into one company "
            f"average.\n\n{wf_table}"
        )

    delta_rows = []
    for wf in sorted(set(pre_wf.index) & set(post_wf.index)):
        a = pre_wf.loc[wf, "accept_rate"]
        b = post_wf.loc[wf, "accept_rate"]
        if pd.isna(a) or pd.isna(b):
            continue
        delta_rows.append(
            [str(wf), fmt_pct(a).strip(), fmt_pct(b).strip(), f"{100 * (b - a):+.1f} pp"]
        )
    delta_table = (
        block_table(["workflow", "before", "after", "change"], delta_rows)
        if delta_rows
        else "   (no comparable pre/post data)"
    )
    lines.append(
        f"2. Do not roll the {change_date.date()} prompt change out broadly "
        "yet. Accept-rate effects are small and mixed across workflows:\n\n"
        f"{delta_table}\n\n"
        "   The post-change period is short, and the same week contains a "
        "demo-traffic spike and a review-policy shock — not enough evidence "
        "to establish a company-wide improvement."
    )

    shock = add_rates(clean_df.loc[clean_df["policy_shock"]].copy())
    if not shock.empty:
        r = shock.iloc[0]
        typical = usable[
            (usable["workflow"] == r["workflow"]) & ~usable["policy_shock"]
        ]
        anomaly_table = block_table(
            ["metric", f"typical {r['workflow']}", str(r["date"].date())],
            [
                [
                    "accept rate",
                    fmt_pct(weighted_rate(typical, "accepted_output", "completed")).strip(),
                    fmt_pct(r["accept_rate"]).strip(),
                ],
                [
                    "flag rate",
                    fmt_pct(weighted_rate(typical, "flagged_for_review", "completed")).strip(),
                    fmt_pct(r["flag_rate"]).strip(),
                ],
                [
                    "confidence",
                    fmt_num(typical["median_confidence"].median()),
                    fmt_num(r["median_confidence"]),
                ],
                [
                    "rating",
                    fmt_num(typical["user_rating"].mean(), 1),
                    fmt_num(r["user_rating"], 1),
                ],
            ],
        )
        lines.append(
            f"3. Investigate {r['workflow']} / {r['date'].date()} first. The "
            f"review policy changed mid-day ({r['source']}), and the day broke "
            "away from every typical number while model confidence stayed "
            "high:\n\n"
            f"{anomaly_table}\n\n"
            "   Determine whether the deterioration came from the stricter "
            "policy, the new prompt, or an interaction between the two. "
            "This is the first "
            "issue to investigate because the drop is concentrated in one "
            "day and coincides with a known operational change, making it "
            "both high-impact and actionable."
        )
    else:
        lines.append(
            "3. Before a broader rollout, inspect the workflow with the highest "
            "flag rate and any day where accept rate and confidence disagree."
        )

    demo = clean_df.loc[clean_df["exclude_from_metrics"]]
    demo_rating = demo["user_rating"].max() if not demo.empty else float("nan")
    min_by_wf = (
        {str(k): float(v) for k, v in by_wf.set_index("workflow")["avg_minutes_saved"].items()}
        if not by_wf.empty
        else {}
    )
    min_bits = ", ".join(f"{k} {v:.1f} min" for k, v in min_by_wf.items()) or "n/a"
    rating_note = (
        f" and is sensitive to the demo spike ({demo_rating})"
        if pd.notna(demo_rating)
        else ""
    )
    lines.append(
        "4. Do not use softer metrics as standalone quality rankings.\n"
        "   - avg_minutes_saved mainly reflects task complexity, not "
        f"workflow quality ({min_bits}), and is an unweighted mean of "
        "daily rows.\n"
        "   - median_confidence is a diagnostic signal, not a user outcome; "
        "on the policy-shock day it stayed high while acceptance collapsed.\n"
        f"   - user_rating is too sparse to be a primary KPI{rating_note}.\n"
        "   Use accept rate and flag rate as primary health metrics; use "
        "confidence and rating as secondary diagnostics."
    )
    lines.append(
        "5. Weekly monitoring rule going forward:\n"
        "   (1) remove near-duplicate export rows and demo/test traffic;\n"
        "   (2) report accept rate and flag rate by workflow — never a "
        "blended company average;\n"
        "   (3) annotate prompt and policy changes next to the numbers;\n"
        "   (4) investigate any accept-rate drop of more than 10 pp "
        "day-over-day;\n"
        "   (5) investigate any doubling of flag rate;\n"
        "   (6) recalibrate these initial thresholds as history accumulates "
        "(they are not derived from this one week)."
    )
    return lines


def run(path: Path) -> None:
    raw = load_raw(path)
    cleaned, quality_flags, context_flags = clean(raw)

    print("=" * 72)
    print("SignalDesk weekly health check")
    print(f"Window: {period_label(raw)}  |  source: {path}")
    print("=" * 72)
    print()
    print("This is not a quality scorecard. completed != good output.")
    print("accepted_output is a rough 'no major rework' signal, not a label.")
    print("median_confidence is model-reported confidence, not correctness.")
    print("All rates below use the cleaned slice: near-duplicate export rows")
    print("and demo traffic removed, policy-shock day kept but shown separately.")

    print()
    print("WHAT TO DO NEXT")
    print("---------------")
    for line in build_recommendation(cleaned):
        print(line)
        print()

    print("DATA QUALITY FLAGS (broken records, fixed or dropped)")
    print("------------------------------------------------------")
    for i, flag in enumerate(quality_flags, 1):
        print(f"{i}. {flag}")

    print()
    print("CONTEXT FLAGS (valid records that change how to read the numbers)")
    print("------------------------------------------------------------------")
    for i, flag in enumerate(context_flags, 1):
        print(f"{i}. {flag}")


def main() -> None:
    parser = argparse.ArgumentParser(description="SignalDesk weekly health check")
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA,
        help="Path to product_usage_events.csv",
    )
    args = parser.parse_args()
    if not args.data.exists():
        raise SystemExit(f"Data file not found: {args.data}")
    run(args.data)


if __name__ == "__main__":
    main()
