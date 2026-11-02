"""Turn raw Sofascore JSON into flat rows. Pure functions, no network."""
from __future__ import annotations

from datetime import datetime, timezone


def _flatten(prefix: str, value, out: dict) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            _flatten(f"{prefix}_{key}", inner, out)
    elif not isinstance(value, list):
        out[prefix] = value


def event_row(event: dict) -> dict:
    tournament = event.get("tournament") or {}
    unique = tournament.get("uniqueTournament") or {}
    season = event.get("season") or {}
    timestamp = event.get("startTimestamp")
    return {
        "event_id": event.get("id"),
        "date": datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
        if timestamp
        else None,
        "tournament": unique.get("name") or tournament.get("name"),
        "tournament_id": unique.get("id"),
        "season_year": season.get("year"),
        "season_id": season.get("id"),
        "round": (event.get("roundInfo") or {}).get("round"),
        "home": (event.get("homeTeam") or {}).get("name"),
        "away": (event.get("awayTeam") or {}).get("name"),
        "home_score": (event.get("homeScore") or {}).get("current"),
        "away_score": (event.get("awayScore") or {}).get("current"),
        "status": (event.get("status") or {}).get("type"),
    }


def player_match_row(event: dict, lineups: dict | None, player_id: int) -> dict | None:
    """The player's line in one match's lineup (stats, rating, position)."""
    if not lineups:
        return None
    for side in ("home", "away"):
        for entry in (lineups.get(side) or {}).get("players", []):
            if (entry.get("player") or {}).get("id") != player_id:
                continue
            own = event.get("homeTeam" if side == "home" else "awayTeam") or {}
            other = event.get("awayTeam" if side == "home" else "homeTeam") or {}
            row = {
                "event_id": event.get("id"),
                "side": side,
                "team": own.get("name"),
                "opponent": other.get("name"),
                "position": entry.get("position"),
                "substitute": entry.get("substitute"),
                "shirt": entry.get("shirtNumber"),
            }
            _flatten("stat", entry.get("statistics") or {}, row)
            return row
    return None


def shot_rows(event: dict, shotmap: dict | None, player_id: int) -> list[dict]:
    rows = []
    for shot in (shotmap or {}).get("shotmap", []):
        if (shot.get("player") or {}).get("id") != player_id:
            continue
        coords = shot.get("playerCoordinates") or {}
        rows.append(
            {
                "event_id": event.get("id"),
                "minute": shot.get("time"),
                "shot_type": shot.get("shotType"),
                "situation": shot.get("situation"),
                "body_part": shot.get("bodyPart"),
                "xg": shot.get("xg"),
                "xgot": shot.get("xgot"),
                "x": coords.get("x"),
                "y": coords.get("y"),
            }
        )
    return rows
