"""Offline tests: a fake transport stands in for Sofascore.

The response shapes here follow the undocumented Sofascore API as I know it.
They prove the pipeline logic; only `probe` against the live site proves the
shapes still match reality.
"""
import pandas as pd
import pytest

from sfresearch.client import BlockedError, Client
from sfresearch.collect import collect
from sfresearch.report import build_report

PID = 750


def ev(eid, ts, home, away, year, status="finished", tournament="LaLiga"):
    return {
        "id": eid,
        "startTimestamp": ts,
        "status": {"type": status},
        "tournament": {"uniqueTournament": {"id": 8, "name": tournament}},
        "season": {"id": 100 + int(year[:2]), "year": year},
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "homeScore": {"current": 2},
        "awayScore": {"current": 1},
    }


def lineups(goals, rating, minutes=90):
    ronaldo = {
        "player": {"id": PID},
        "position": "F",
        "substitute": False,
        "shirtNumber": 7,
        "statistics": {
            "minutesPlayed": minutes,
            "goals": goals,
            "goalAssist": 0,
            "rating": rating,
            "ratingVersions": {"original": rating, "alternative": rating},
        },
    }
    return {
        "home": {"players": [ronaldo, {"player": {"id": 1}, "statistics": {"goals": 9}}]},
        "away": {"players": []},
    }


class FakeTransport:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        return self.routes.get(path, (404, None))


def routes():
    return {
        f"/player/{PID}": (200, {"player": {"id": PID, "name": "Cristiano Ronaldo"}}),
        f"/player/{PID}/events/last/0": (
            200,
            {
                "events": [
                    ev(1, 1_500_000_000, "Real Madrid", "Sevilla", "16/17"),
                    ev(2, 1_490_000_000, "Real Madrid", "Betis", "16/17", status="postponed"),
                ],
                "hasNextPage": True,
            },
        ),
        f"/player/{PID}/events/last/1": (
            200,
            {"events": [ev(3, 1_100_000_000, "Man United", "Chelsea", "04/05", tournament="Premier League")],
             "hasNextPage": False},
        ),
        "/event/1/lineups": (200, lineups(2, 8.1)),
        "/event/1/shotmap": (
            200,
            {"shotmap": [
                {"player": {"id": PID}, "xg": 0.4, "time": 12, "shotType": "goal", "playerCoordinates": {"x": 8, "y": 50}},
                {"player": {"id": 1}, "xg": 0.9, "time": 30},
            ]},
        ),
        # event 3 has no lineup coverage (404 by default) -> should be reported as a gap
    }


def make_client(tmp_path, transport, **kw):
    return Client(transport, tmp_path / "raw", sleep=lambda s: None, uniform=lambda a, b: 0, **kw)


def test_collect_report_and_cache(tmp_path):
    transport = FakeTransport(routes())
    client = make_client(tmp_path, transport)
    stats = collect(client, PID, tmp_path, log=lambda *_: None)

    assert stats["events"] == 3
    assert stats["finished_considered"] == 2  # postponed event skipped
    assert stats["with_lineup_stats"] == 1  # event 3 has no lineup data
    assert stats["shots"] == 1  # teammate's shot excluded

    matches = pd.read_csv(tmp_path / "player_matches.csv")
    assert matches.loc[0, "stat_goals"] == 2
    assert matches.loc[0, "stat_ratingVersions_original"] == 8.1  # nested stats flattened
    assert matches.loc[0, "opponent"] == "Sevilla"

    summary, coverage = build_report(tmp_path)
    row = summary[summary.season_year == "16/17"].iloc[0]
    assert (row.matches, row.goals, row.xg, row.avg_rating) == (1, 2, 0.4, 8.1)
    gap = coverage[coverage.season_year == "04/05"].iloc[0]
    assert (gap.finished_events, gap.with_lineup_stats) == (1, 0)

    # Second run is served entirely from cache.
    transport.calls.clear()
    client2 = make_client(tmp_path, transport)
    collect(client2, PID, tmp_path, log=lambda *_: None)
    assert transport.calls == []


def test_block_raises_and_partial_output_is_written(tmp_path):
    r = routes()
    r["/event/1/lineups"] = (403, None)
    client = make_client(tmp_path, FakeTransport(r), max_retries=2)
    with pytest.raises(BlockedError):
        collect(client, PID, tmp_path, log=lambda *_: None)
    assert (tmp_path / "events.csv").exists()
    assert (tmp_path / "player_matches.csv").exists()  # written in `finally`


def test_since_filter(tmp_path):
    client = make_client(tmp_path, FakeTransport(routes()))
    stats = collect(client, PID, tmp_path, since="2016-01-01", log=lambda *_: None)
    assert stats["finished_considered"] == 1
