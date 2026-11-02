"""Command line: search | probe | collect | report."""
from __future__ import annotations

import argparse
from pathlib import Path

from .client import BlockedError, Client
from .collect import collect, fetch_player
from .report import build_report
from .transport import CurlTransport, PlaywrightTransport

DEFAULT_PLAYER_ID = 750  # Cristiano Ronaldo on Sofascore (unverified: `collect` checks the name)
DEFAULT_EXPECT = "Ronaldo"


def _client(args, cache: bool = True) -> Client:
    cache_dir = Path(args.out) / "raw" if cache else None
    if args.transport == "playwright":
        transport = PlaywrightTransport(headless=args.headless)
        import atexit

        atexit.register(transport.close)
    else:
        transport = CurlTransport(impersonate=args.impersonate)
    return Client(
        transport,
        cache_dir,
        delay=(args.delay_min, args.delay_max),
    )


def cmd_search(args) -> None:
    client = _client(args, cache=False)
    from urllib.parse import quote

    data = client.get(f"/search/all?q={quote(args.query)}") or {}
    for result in data.get("results", []):
        entity = result.get("entity") or {}
        if result.get("type") == "player":
            team = (entity.get("team") or {}).get("name", "")
            print(f"{entity.get('id'):>10}  {entity.get('name')}  ({team})")


def cmd_probe(args) -> None:
    """Hit each endpoint once and show what comes back, so you can see what works."""
    client = _client(args)
    pid = args.player_id
    player = fetch_player(client, pid)
    print(f"player: {player.get('name')} (id {pid})")
    page = client.get(f"/player/{pid}/events/last/0") or {}
    listed = page.get("events", [])
    print(f"events/last/0: {len(listed)} events, hasNextPage={page.get('hasNextPage')}")
    finished = [e for e in listed if (e.get("status") or {}).get("type") == "finished"]
    if not finished:
        print("no finished event on page 0; cannot probe per-match endpoints")
        return
    eid = finished[0]["id"]
    for label, path in (
        ("lineups", f"/event/{eid}/lineups"),
        ("shotmap", f"/event/{eid}/shotmap"),
        ("heatmap", f"/event/{eid}/player/{pid}/heatmap"),
    ):
        data = client.get(path)
        keys = sorted(data) if isinstance(data, dict) else None
        print(f"{label:8} event {eid}: {'missing (404)' if data is None else f'ok, keys={keys}'}")


def cmd_collect(args) -> None:
    client = _client(args)
    player = fetch_player(client, args.player_id)
    name = player.get("name", "")
    print(f"player: {name} (id {args.player_id})")
    if args.expect_name and args.expect_name.lower() not in name.lower():
        raise SystemExit(
            f"Name check failed: expected '{args.expect_name}' but id {args.player_id} is '{name}'."
        )
    try:
        stats = collect(
            client,
            args.player_id,
            Path(args.out),
            heatmaps=args.heatmaps,
            limit=args.limit,
            since=args.since,
        )
    except BlockedError as exc:
        raise SystemExit(f"Stopped: {exc}")
    print(stats)


def cmd_report(args) -> None:
    summary, coverage = build_report(Path(args.out))
    print("\nCoverage by season (finished matches vs matches with lineup stats / rating):")
    print(coverage.to_string(index=False))
    print("\nSummary by season and competition:")
    print(summary.to_string(index=False))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="sfresearch", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p, player=True):
        p.add_argument("--out", default="data/ronaldo", help="output folder (raw cache goes in <out>/raw)")
        p.add_argument("--delay-min", type=float, default=1.5)
        p.add_argument("--delay-max", type=float, default=3.0)
        p.add_argument("--transport", choices=["curl", "playwright"], default="curl",
                       help="curl = fast HTTP with browser fingerprint; playwright = real Chromium")
        p.add_argument("--impersonate", default="chrome",
                       help="curl_cffi fingerprint, e.g. chrome, chrome131, safari17_0, edge101")
        p.add_argument("--headless", action="store_true",
                       help="with --transport playwright: hide the browser window (more likely to be blocked)")
        if player:
            p.add_argument("--player-id", type=int, default=DEFAULT_PLAYER_ID)

    p = sub.add_parser("search", help="find a player's Sofascore id")
    p.add_argument("query")
    common(p, player=False)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("probe", help="check which endpoints respond")
    common(p)
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("collect", help="collect all matches for a player")
    common(p)
    p.add_argument("--expect-name", default=None, help="abort unless the player's name contains this")
    p.add_argument("--heatmaps", action="store_true", help="also fetch per-match heatmaps (slow)")
    p.add_argument("--limit", type=int, default=None, help="only process N matches (for a trial run)")
    p.add_argument("--since", default=None, help="only matches on/after YYYY-MM-DD")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("report", help="season/competition summary and coverage gaps (offline)")
    common(p, player=False)
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    if args.cmd == "collect" and args.expect_name is None and args.player_id == DEFAULT_PLAYER_ID:
        args.expect_name = DEFAULT_EXPECT
    try:
        args.func(args)
    except BlockedError as exc:
        raise SystemExit(f"Blocked: {exc}")
