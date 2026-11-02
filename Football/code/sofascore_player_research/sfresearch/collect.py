"""Collect one player's matches: event list -> lineup stats, shots, heatmaps."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .client import Client
from .flatten import event_row, player_match_row, shot_rows

MAX_PAGES = 300  # safety stop; ~30 events per page


def fetch_player(client: Client, player_id: int) -> dict:
    data = client.get(f"/player/{player_id}")
    if not data or "player" not in data:
        raise SystemExit(f"Player {player_id} not found. Use the `search` command to find the id.")
    return data["player"]


def fetch_events(client: Client, player_id: int) -> list[dict]:
    """All events the player is listed in, newest first, de-duplicated."""
    events, seen = [], set()
    for page in range(MAX_PAGES):
        data = client.get(f"/player/{player_id}/events/last/{page}")
        if not data:
            break
        for event in data.get("events", []):
            if event.get("id") not in seen:
                seen.add(event.get("id"))
                events.append(event)
        if not data.get("hasNextPage"):
            break
    return events


def collect(
    client: Client,
    player_id: int,
    out_dir: Path,
    *,
    heatmaps: bool = False,
    limit: int | None = None,
    since: str | None = None,
    log=print,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    events = fetch_events(client, player_id)
    rows = [event_row(e) for e in events]
    events_df = pd.DataFrame(rows)
    events_df.to_csv(out_dir / "events.csv", index=False)
    log(f"{len(events)} events listed for player {player_id}")

    todo = [
        e
        for e, r in zip(events, rows)
        if r["status"] == "finished" and (not since or (r["date"] or "") >= since)
    ]
    if limit:
        todo = todo[:limit]

    matches, shots, heat = [], [], 0
    try:
        for i, event in enumerate(todo, 1):
            eid = event["id"]
            lineups = client.get(f"/event/{eid}/lineups")
            row = player_match_row(event, lineups, player_id)
            if row is None:
                continue  # not in lineup data (e.g. unused sub, or no coverage)
            shotmap = client.get(f"/event/{eid}/shotmap")
            shots.extend(shot_rows(event, shotmap, player_id))
            if heatmaps and client.get(f"/event/{eid}/player/{player_id}/heatmap"):
                heat += 1
            matches.append(row)
            if i % 25 == 0:
                log(f"  {i}/{len(todo)} matches processed")
    finally:  # write whatever we have, even on Ctrl-C or a block
        pd.DataFrame(matches).to_csv(out_dir / "player_matches.csv", index=False)
        pd.DataFrame(shots).to_csv(out_dir / "shots.csv", index=False)

    return {
        "events": len(events),
        "finished_considered": len(todo),
        "with_lineup_stats": len(matches),
        "shots": len(shots),
        "heatmaps": heat,
        "network_calls": client.network_calls,
    }
