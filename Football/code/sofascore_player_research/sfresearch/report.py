"""Summaries and coverage gaps from the collected CSVs (no network)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def _read(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def _num(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df:
        return pd.to_numeric(df[column], errors="coerce").fillna(0)
    return pd.Series(0, index=df.index, dtype=float)


def build_report(out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    events = _read(out_dir / "events.csv")
    matches = _read(out_dir / "player_matches.csv")
    shots = _read(out_dir / "shots.csv")
    if events.empty:
        raise SystemExit("No events.csv found. Run `collect` first.")

    finished = events[events["status"] == "finished"]
    joined = finished.merge(matches, on="event_id", how="left", indicator="_m")
    joined["has_stats"] = joined["_m"] == "both"
    rating = pd.to_numeric(joined.get("stat_rating"), errors="coerce")
    joined["has_rating"] = rating.notna()

    coverage = (
        joined.groupby("season_year", dropna=False)
        .agg(
            finished_events=("event_id", "count"),
            with_lineup_stats=("has_stats", "sum"),
            with_rating=("has_rating", "sum"),
        )
        .reset_index()
        .sort_values("season_year")
    )

    played = joined[joined["has_stats"]].copy()
    played["minutes"] = _num(played, "stat_minutesPlayed")
    played["goals"] = _num(played, "stat_goals")
    played["assists"] = _num(played, "stat_goalAssist")
    played["rating"] = pd.to_numeric(played.get("stat_rating"), errors="coerce")
    if not shots.empty:
        xg = shots.assign(xg=pd.to_numeric(shots["xg"], errors="coerce")).groupby(
            "event_id", as_index=False
        )["xg"].sum()
        played = played.merge(xg, on="event_id", how="left")
    else:
        played["xg"] = float("nan")

    summary = (
        played.groupby(["season_year", "tournament"], dropna=False)
        .agg(
            matches=("event_id", "count"),
            minutes=("minutes", "sum"),
            goals=("goals", "sum"),
            assists=("assists", "sum"),
            xg=("xg", "sum"),
            avg_rating=("rating", "mean"),
        )
        .reset_index()
        .sort_values(["season_year", "tournament"])
    )
    summary["avg_rating"] = summary["avg_rating"].round(2)
    summary["xg"] = summary["xg"].round(2)

    summary.to_csv(out_dir / "summary_by_season_competition.csv", index=False)
    coverage.to_csv(out_dir / "coverage_by_season.csv", index=False)
    return summary, coverage
