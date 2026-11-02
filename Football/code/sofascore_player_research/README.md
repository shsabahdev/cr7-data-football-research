# Sofascore player research collector

Collects every match for one player from Sofascore's undocumented JSON API
(the same API that `datafc`, `soccerdata` and `pysofascore` wrap) and turns it
into CSVs: a match list, per-match lineup stats with rating, shots with xG, and
optional heatmaps. Built for **personal, non-commercial research**.

## Read this first

- **Unofficial.** Sofascore does not license API access. Its Terms of Service
  may forbid scraping; I could not read them. Keep to personal research, use
  the default delays, and do not redistribute the data.
- **Not tested against the live site.** I built this in a sandbox that could
  not reach Sofascore or install the libraries above, so endpoint shapes come
  from my knowledge of the API. The offline tests prove the pipeline logic
  only. **Run `probe` first**; it shows which endpoints respond.
- **Player id 750 is my recollection of Ronaldo's id.** `collect` checks the
  player's name and aborts on a mismatch, so a wrong id cannot silently
  collect the wrong player.
- Old matches often have no lineup stats or ratings. `report` lists those gaps
  per season instead of hiding them.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Use

```bash
python -m sfresearch probe                       # 1. does it work from your network?
python -m sfresearch collect --limit 20          # 2. trial run on 20 matches
python -m sfresearch collect                     # 3. full run (hours; resumable)
python -m sfresearch report                      # 4. summaries + coverage gaps, offline
```

Outputs go to `data/ronaldo/`:

| File | Content |
|---|---|
| `events.csv` | every match listed for the player (date, competition, season, teams, score, status) |
| `player_matches.csv` | his line per match: team, opponent, position, minutes, goals, assists, rating, all other lineup stats (`stat_*`) |
| `shots.csv` | his shots: minute, type, situation, body part, xG, xGOT, coordinates |
| `summary_by_season_competition.csv` | matches, minutes, goals, assists, xG, average rating |
| `coverage_by_season.csv` | finished matches vs matches with lineup stats vs with rating |
| `raw/` | every raw JSON response; reruns and `report` never hit the network for these |

Useful flags: `--since 2018-01-01`, `--heatmaps`, `--delay-min 3 --delay-max 6`
(slower is safer).

## Comparing with other players

```bash
python -m sfresearch search "Lionel Messi"       # prints Sofascore ids
python -m sfresearch collect --player-id <id> --expect-name Messi --out data/messi
python -m sfresearch report --out data/messi
```

Each player gets their own folder with identical columns, so the CSVs can be
concatenated for comparison.

## If it gets blocked (HTTP 403)

Sofascore sits behind Cloudflare. The client retries with backoff, then stops
and prints what the server said (`server=`, `cf-mitigated=`, start of the body)
rather than hammering the site. Progress is cached. Try, in this order:

1. **Real browser:** `pip install playwright && python -m playwright install chromium`,
   then `python -m sfresearch probe --transport playwright`. A window opens;
   leave it open. If a "verify you are human" page appears, solve it once.
2. **Another fingerprint:** `python -m sfresearch probe --impersonate chrome131`
   (also `safari17_0`, `edge101`).
3. **Another network:** home connection, no VPN or datacenter IP. Block lists
   often cover those.
4. Wait an hour and use slower delays (`--delay-min 4 --delay-max 8`).

All of these are about being a normal-looking client at a polite pace, not
about defeating the site's protection. If none work, the site does not want
automated access from your network, and the other sources (Transfermarkt
dataset, StatsBomb, Wyscout public data, Understat) are the fallback.

## Layout

```
sfresearch/transport.py   Chrome-fingerprint HTTP (curl_cffi); swappable
sfresearch/client.py      cache, jittered delay, backoff, stop-on-block
sfresearch/flatten.py     raw JSON -> rows (pure functions)
sfresearch/collect.py     event list -> lineups, shots, heatmaps
sfresearch/report.py      season/competition summary and coverage gaps
tests/test_pipeline.py    offline tests with a fake transport
```
