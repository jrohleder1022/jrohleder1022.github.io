#!/usr/bin/env python3
"""Rank waiver-wire receivers by projected PPR points per game.

    python3 waiver_wr.py "Jerry Jeudy" "Antonio Williams" "Pat Bryant"
    python3 waiver_wr.py --selftest

Why this model looks the way it does
------------------------------------
Every read that went right this season came from targets, and every read that
went wrong came from scoring. Diggs looked like an 18.6-a-game receiver on
three touchdowns in fifteen targets; strip the scores and he was 9.6, and 9.6
is what he turned into. Golden's twelve-target opener got priced as a role and
his next game was six. Egbuka's sixteen-target week was visible a month before
his average caught up to it.

So the projection is built from the parts that persist, in this order:

  1. Targets per game, weighted toward the last three games. Role changes
     mid-season and the recent window sees it first.
  2. Catch rate. In PPR a catch is a point, so converting targets matters as
     much as drawing them. McConkey at 80% and Quentin Johnston at 39% saw
     nearly the same volume and scored very differently.
  3. Yards per catch, which is stable and which nobody has to regress.
  4. Touchdowns, regressed hard toward the league rate. This is the only
     component the model actively distrusts.

The output is in PPR points per game so it compares directly against whoever
is in your lineup now, rather than an index number that means nothing on its
own. The component columns are printed alongside, because a projection you
cannot argue with is a projection you cannot correct.

Scoring assumed: 1 per reception, 0.1 per yard, 6 per touchdown.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ESPN_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search"
ESPN_GAMELOG = (
    "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl"
    "/athletes/{aid}/gamelog"
)
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".waiver_cache")

# Share of targets a receiver turns into a touchdown, league-wide. Every
# player's own rate is pulled toward this; see regressed_td_rate.
LEAGUE_TD_PER_TARGET = 0.055
# Strength of that pull, in targets. At 30, a player needs ~30 targets before
# his own rate carries more weight than the league's. Chosen so that a Diggs
# (3 scores in 15 targets) lands near 9%, not 20%.
TD_PRIOR_TARGETS = 30
# How much the last three games outweigh the rest of the season.
RECENT_GAMES = 3
RECENT_WEIGHT = 0.60


# --------------------------------------------------------------------------
# the model
# --------------------------------------------------------------------------

def regressed_td_rate(tds, targets):
    """Blend a player's touchdown rate toward the league's."""
    return (tds + TD_PRIOR_TARGETS * LEAGUE_TD_PER_TARGET) / (
        targets + TD_PRIOR_TARGETS
    )


def blend(recent, season, weight=RECENT_WEIGHT):
    if recent is None:
        return season
    return weight * recent + (1 - weight) * season


def project(games, weeks=None):
    """games: list of dicts with rec, tgt, yds, td. Newest first.

    weeks: how many games his team has played. A receiver who has appeared in
    four of nine is hurt, buried, or both, and rest-of-season he will keep
    costing you the weeks he misses — so the ranking uses availability, while
    PROJ stays per-game so it compares against whoever starts for you now.

    Returns the projection plus every component that fed it.
    """
    if not games:
        return None

    played = len(games)
    tgt = sum(g["tgt"] for g in games)
    rec = sum(g["rec"] for g in games)
    yds = sum(g["yds"] for g in games)
    tds = sum(g["td"] for g in games)

    recent = games[:RECENT_GAMES]
    r_tgt = sum(g["tgt"] for g in recent)
    r_rec = sum(g["rec"] for g in recent)
    r_yds = sum(g["yds"] for g in recent)

    tgt_pg = blend(r_tgt / len(recent), tgt / played)
    catch_rate = blend(
        (r_rec / r_tgt) if r_tgt else None,
        (rec / tgt) if tgt else 0.0,
    )
    ypc = blend(
        (r_yds / r_rec) if r_rec else None,
        (yds / rec) if rec else 0.0,
    )
    td_rate = regressed_td_rate(tds, tgt)

    catches = tgt_pg * catch_rate
    proj = catches + (catches * ypc * 0.1) + (tgt_pg * td_rate * 6)

    # What he actually scored, and what he scored with the end zone removed.
    actual = (rec + yds * 0.1 + tds * 6) / played
    td_free = (rec + yds * 0.1) / played

    # Direction of the role, not of the scoring: targets per game over the
    # recent window against everything before it. This is the column that
    # would have flagged Golden's collapse and Egbuka's breakout early.
    prior = games[RECENT_GAMES:]
    trend = None
    if prior:
        trend = (r_tgt / len(recent)) - (
            sum(g["tgt"] for g in prior) / len(prior)
        )

    avail = 1.0 if not weeks else min(1.0, played / float(weeks))

    return {
        "games": played,
        "weeks": weeks,
        "avail": avail,
        "proj": proj,
        "expected": proj * avail,
        "actual": actual,
        "td_free": td_free,
        "tgt_pg": tgt_pg,
        "catch_rate": catch_rate,
        "ypc": ypc,
        "td_rate": td_rate,
        "trend": trend,
    }


# --------------------------------------------------------------------------
# espn
# --------------------------------------------------------------------------

def _get(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "waiver-wr/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def resolve(name):
    """Name -> (athlete_id, display name, team). Returns None if not found."""
    try:
        d = _get(ESPN_SEARCH, {"region": "us", "lang": "en",
                               "query": name, "limit": 8})
    except Exception as e:
        raise RuntimeError("search failed for %r: %s" % (name, e))
    for group in d.get("results", []):
        for item in group.get("contents", []):
            if item.get("type") != "player":
                continue
            link = item.get("link", {}).get("web", "") or ""
            if "/nfl/" not in link:
                continue
            uid = item.get("uid", "")
            aid = uid.rsplit("a:", 1)[-1] if "a:" in uid else None
            if not aid:
                parts = [p for p in link.split("/") if p.isdigit()]
                aid = parts[0] if parts else None
            if aid:
                return aid, item.get("displayName", name), item.get("subtitle", "")
    return None


def _stat_index(payload):
    """Map stat name -> column index, from whichever key ESPN populates."""
    for key in ("names", "labels", "displayNames"):
        cols = payload.get(key)
        if cols:
            return {str(c).lower(): i for i, c in enumerate(cols)}
    return {}


def _pick(idx, row, *candidates):
    for c in candidates:
        i = idx.get(c.lower())
        if i is not None and i < len(row):
            raw = str(row[i]).replace(",", "").strip()
            if raw in ("", "-", "--"):
                return 0.0
            try:
                return float(raw)
            except ValueError:
                return 0.0
    return 0.0


def gamelog(aid, use_cache=True):
    """Fetch a receiving game log. Newest game first."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "%s.json" % aid)
    payload = None
    if use_cache and os.path.exists(path) and time.time() - os.path.getmtime(path) < 43200:
        payload = json.load(open(path))
    if payload is None:
        payload = _get(ESPN_GAMELOG.format(aid=aid))
        try:
            json.dump(payload, open(path, "w"))
        except OSError:
            pass

    idx = _stat_index(payload)
    if not idx:
        raise RuntimeError("could not read the stat columns ESPN returned")

    games = []
    for st in payload.get("seasonTypes", []):
        if "regular" not in str(st.get("displayName", "")).lower():
            continue
        for cat in st.get("categories", []):
            for ev in cat.get("events", []):
                row = ev.get("stats") or []
                if not row:
                    continue
                games.append({
                    "rec": _pick(idx, row, "receivingReceptions", "rec"),
                    "tgt": _pick(idx, row, "receivingTargets", "tgts", "tgt"),
                    "yds": _pick(idx, row, "receivingYards", "yds"),
                    "td":  _pick(idx, row, "receivingTouchdowns", "td"),
                })
    # ESPN returns newest first inside a season type; keep that order.
    return [g for g in games if g["tgt"] or g["rec"]]


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------

HEAD = ("%-22s %7s %6s %6s %6s %7s %6s %6s %6s %7s" %
        ("PLAYER", "GMS", "EXP", "PROJ", "ACTUAL", "TD-FREE",
         "TGT/G", "CATCH%", "YDS/C", "TREND"))


def row(name, m):
    trend = "    -- " if m["trend"] is None else "%+6.1f " % m["trend"]
    gms = ("%d/%d" % (m["games"], m["weeks"])) if m["weeks"] else str(m["games"])
    return ("%-22s %7s %6.1f %6.1f %6.1f %7.1f %6.1f %5.0f%% %6.1f %s" % (
        name[:22], gms, m["expected"], m["proj"], m["actual"], m["td_free"],
        m["tgt_pg"], m["catch_rate"] * 100, m["ypc"], trend))


def report(rows, note=None):
    # Rank on EXP — points per week of the season, which is what a roster spot
    # actually buys. PROJ is per game played and is shown beside it so a
    # part-time producer is visible rather than hidden.
    rows.sort(key=lambda r: -r[1]["expected"])
    print()
    print(HEAD)
    print("-" * len(HEAD))
    for name, m in rows:
        print(row(name, m))
    print()
    if rows:
        best, m = rows[0]
        print("Best available: %s at %.1f a week." % (best, m["expected"]))
        if m["avail"] < 0.8:
            print("  He has only played %d of %d, so %.1f of that is the "
                  "availability discount. Find out why before you claim him."
                  % (m["games"], m["weeks"], m["proj"] - m["expected"]))
        if m["trend"] is not None and m["trend"] > 1.5:
            print("  His targets are up %.1f a game over the last %d — the role is "
                  "still growing, so treat the projection as a floor."
                  % (m["trend"], RECENT_GAMES))
        if m["actual"] - m["td_free"] > 5:
            print("  Note: %.1f of his %.1f average is touchdowns. The projection "
                  "already discounts that; his raw average will fall."
                  % (m["actual"] - m["td_free"], m["actual"]))
    if note:
        print()
        print(note)


# --------------------------------------------------------------------------
# selftest — real 2026 lines gathered this season, newest game first
# --------------------------------------------------------------------------

FIXTURES = {
    # name: [(rec, tgt, yds, td), ...] newest first
    "Emeka Egbuka": [(7, 16, 48, 1), (6, 9, 38, 0), (2, 4, 13, 0),
                     (5, 9, 62, 0), (3, 5, 16, 1), (5, 6, 63, 0)],
    "George Pickens": [(2, 4, 48, 0), (4, 6, 57, 1), (6, 11, 73, 0),
                       (9, 13, 130, 1), (2, 3, 75, 0), (7, 11, 82, 0),
                       (6, 8, 40, 0), (3, 6, 28, 0)],
    "Ladd McConkey": [(4, 5, 66, 0), (3, 3, 35, 0), (5, 7, 82, 1)],
    "Stefon Diggs": [(4, 7, 33, 0), (5, 6, 47, 2), (4, 9, 55, 1)],
    "Pat Bryant": [(4, 5, 56, 1), (3, 3, 47, 0), (2, 2, 44, 1),
                   (0, 1, 0, 0), (4, 6, 42, 0)],
    "Marvin Harrison Jr.": [(2, 3, 20, 0), (1, 4, 6, 1), (3, 4, 34, 0),
                            (1, 4, 12, 1), (3, 5, 40, 0), (0, 1, 0, 0),
                            (1, 3, 33, 0)],
    "Jerry Jeudy": [(4, 4, 69, 0), (3, 7, 19, 0), (3, 3, 36, 0),
                    (0, 0, 0, 0), (0, 1, 0, 0), (2, 4, 26, 0)],
    "Quentin Johnston": [(1, 3, 57, 0), (1, 2, 44, 0), (3, 6, 40, 0),
                         (1, 5, 7, 0), (2, 6, 17, 0)],
    "Antonio Williams": [(3, 3, 31, 0), (3, 8, 21, 0), (2, 4, 15, 0),
                         (3, 3, 24, 0), (4, 4, 64, 1)],
    "Ted Hurst III": [(3, 6, 40, 0), (0, 0, 0, 0), (2, 3, 25, 0),
                      (1, 4, 40, 1), (2, 7, 27, 0), (3, 3, 36, 0)],
}


def selftest(weeks=9):
    rows = []
    for name, log in FIXTURES.items():
        games = [{"rec": r, "tgt": t, "yds": y, "td": d} for r, t, y, d in log]
        m = project(games, weeks=weeks)
        if m:
            rows.append((name, m))
    report(rows, note=(
        "Fixture data, not a live pull: real 2026 lines, but each one ends "
        "wherever I\nlast pulled it, so the GMS column understates anyone I "
        "checked early. Diggs\nand McConkey are the clearest cases — their "
        "logs stop at Week 3 and Week 6.\nIn live mode ESPN returns the full "
        "season and the column means what it says.\n\nDiggs is here as a "
        "control. His 14.8 average is carried by three early\ntouchdowns and "
        "the projection should land well under it."
    ))

    d = dict(rows)["Stefon Diggs"]
    assert d["proj"] < d["actual"] - 1.5, "TD regression is not biting on Diggs"
    e = dict(rows)["Emeka Egbuka"]
    assert e["trend"] >= 2.5, "target trend is not catching Egbuka's 16-target week"
    q = dict(rows)["Quentin Johnston"]
    p = dict(rows)["George Pickens"]
    assert p["expected"] > q["expected"] * 1.5, \
        "a 59%-catching 7-target WR should clearly beat a 42%-catching 4-target one"
    print("\nchecks passed: touchdown regression bites, target trend fires, "
          "volume and\ncatch rate separate the real roles from the empty ones.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="receivers on your wire")
    ap.add_argument("--selftest", action="store_true",
                    help="run the model against stored 2026 lines, no network")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--weeks", type=int, default=None,
                    help="games each team has played, for the availability "
                         "discount (default: the most any listed player has)")
    args = ap.parse_args()

    if args.selftest or not args.names:
        if not args.names and not args.selftest:
            print("No names given. Running the self-test instead.\n"
                  "Usage: python3 waiver_wr.py \"Name One\" \"Name Two\" ...",
                  file=sys.stderr)
        selftest()
        return 0

    logs, failed = [], []
    for name in args.names:
        try:
            hit = resolve(name)
            if not hit:
                failed.append((name, "no NFL player by that name"))
                continue
            aid, disp, team = hit
            games = gamelog(aid, use_cache=not args.no_cache)
            logs.append((disp, team, games))
        except Exception as e:
            failed.append((name, str(e)))

    # Without a stated week count, use the busiest log on the board as the
    # baseline. It understates the discount when everyone listed has missed
    # time, so --weeks is there for when you know the real number.
    weeks = args.weeks or (max((len(g) for _, _, g in logs), default=0) or None)

    rows = []
    for disp, team, games in logs:
        m = project(games, weeks=weeks)
        if not m:
            failed.append((disp, "no receiving games logged this season"))
            continue
        label = "%s (%s)" % (disp, team.split(",")[0]) if team else disp
        rows.append((label, m))

    if rows:
        report(rows)
    for name, why in failed:
        print("  skipped %s — %s" % (name, why), file=sys.stderr)
    if not rows:
        print("\nNothing could be ranked. If every name failed with a connection\n"
              "error, this session's network does not allow ESPN; run it from a\n"
              "session on the jrohleder1022.github.io environment.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (only needed for live mode)
    sys.exit(main())
