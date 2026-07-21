"""
One-time historical backfill for the ATP Elo engine, using the
Tennismylife/TML-Database public CSV dataset on GitHub.

BACKGROUND -- READ THIS BEFORE TOUCHING THE URL/SOURCE:
The original plan was to use Jeff Sackmann's tennis_atp repo
(github.com/JeffSackmann/tennis_atp), which for years was THE standard
free source for this kind of data. As of this writing, that repo no
longer exists under his account -- his GitHub profile shows only one
repository (tennis_MatchChartingProject), and every URL that used to
point at tennis_atp now 404s. This was verified directly (not assumed)
by checking his live profile page and repo list.

Tennismylife/TML-Database is a live-maintained, actively-updated
successor/superset covering ATP matches from 1968 to the present
(including in-progress 2026 matches), one CSV file per year, same
core column layout as the old Sackmann files (verified by downloading
and inspecting real files, not assumed from a spec). It's explicitly
described by its maintainers as inspired by and extending Sackmann's
original work.

ATP ONLY: TML-Database does not cover WTA. There is currently no
equivalent free, auto-downloadable, actively-maintained WTA source
found. WTA history stays on the existing day-by-day ESPN accumulation
in the daily pipeline for now -- this script does not touch WTA state.

LICENSE / ATTRIBUTION:
TML-Database states the data is collected from the official ATP
website and other public sources, intended for educational/analytical/
research purposes, and traces its lineage to Sackmann's original
CC BY-NC-SA-licensed work. Same non-commercial spirit applies here:
fine for a personal predictions site, not for reselling the raw data.
Source: https://github.com/Tennismylife/TML-Database

WHAT THIS DOES:
For each requested year, downloads that year's ATP match CSV, parses
every completed singles match, and feeds winner/loser into the SAME
EloEngine save file (elo_state_atp.json) that the daily prediction.py
pipeline reads. After this runs once, the daily pipeline will load
real, populated ATP ratings on its very next run.

This is DELIBERATELY separate from the daily pipeline -- meant to be
run manually, once (or occasionally, e.g. once a year for the newly-
completed season), not on the daily schedule.

HOW TO RUN:
    python3 backfill_from_csv.py

Progress is saved after every year processed. If a single year's
download fails, it's reported and skipped rather than crashing the
whole run -- re-run afterward to retry just the failed years.

NOTE ON RE-RUNS: running this twice against the SAME years will
double-count those matches in the Elo ratings. Run it once against
your target year range. To add a newly-completed season later, edit
BACKFILL_YEARS to just that new year rather than re-running the full
range -- or wipe elo_state_atp.json first if you want a clean redo.
"""
import csv
import io
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, ".")
from prediction import EloEngine, get_surface, get_tier

# Years to pull. More years = more history but a bigger one-time
# download. 2015-present balances recency (today's active players)
# against total sample size reasonably well.
BACKFILL_YEARS = list(range(2015, 2027))  # 2015 through 2026

CSV_URL_TEMPLATE = "https://raw.githubusercontent.com/Tennismylife/TML-Database/master/{year}.csv"
ELO_STATE_PATH = "elo_state_atp.json"

# TML-Database's surface strings match our surface keys except for
# case and the "Carpet" case, which our SURFACES list doesn't have a
# direct entry for -- treat it as the closest analog (indoor hard)
# rather than dropping those matches entirely.
CSV_SURFACE_MAP = {
    "hard": "hard",
    "clay": "clay",
    "grass": "grass",
    "carpet": "indoor_hard",
}


def fetch_csv_rows(url, retries=3, delay=2.0):
    """Downloads a CSV from url and returns parsed rows as a list of
    dicts. Returns None if all retries fail (caller should skip that
    year, not crash the whole backfill)."""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            reader = csv.DictReader(io.StringIO(raw))
            return list(reader)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            print(f"    attempt {attempt}/{retries} failed for {url}: {e}")
            if attempt < retries:
                time.sleep(delay)
    return None


def backfill_atp(years):
    engine = EloEngine()

    existing_since_date = engine.load(ELO_STATE_PATH)
    if existing_since_date:
        print(f"[atp] loaded existing state (was current as of {existing_since_date})")
    else:
        print("[atp] no existing state found -- starting fresh")

    total_fed = 0
    total_skipped = 0
    failed_years = []

    for year in years:
        url = CSV_URL_TEMPLATE.format(year=year)
        print(f"[atp] downloading {year}...")
        rows = fetch_csv_rows(url)

        if rows is None:
            print(f"[atp] {year}: FAILED after retries, skipping this year")
            failed_years.append(year)
            continue

        year_fed = 0
        year_skipped = 0

        for row in rows:
            winner = (row.get("winner_name") or "").strip()
            loser = (row.get("loser_name") or "").strip()
            if not winner or not loser:
                year_skipped += 1
                continue

            score = (row.get("score") or "").strip()
            if not score or "W/O" in score.upper():
                year_skipped += 1
                continue

            csv_surface = (row.get("surface") or "").strip().lower()
            surface = CSV_SURFACE_MAP.get(csv_surface)
            if surface is None:
                surface = get_surface(row.get("tourney_name"))

            tier = get_tier(row.get("tourney_name"))

            engine.update_match(
                winner_name=winner,
                loser_name=loser,
                surface=surface,
                tier=tier,
            )
            year_fed += 1

        total_fed += year_fed
        total_skipped += year_skipped
        print(f"[atp] {year}: fed {year_fed} matches, skipped {year_skipped} "
              f"(running total: {total_fed})")

        engine.save(ELO_STATE_PATH, last_processed_date=None)

    print(f"\n[atp] DONE. Fed {total_fed} total matches across "
          f"{len(years) - len(failed_years)} of {len(years)} years, skipped {total_skipped} rows")
    if failed_years:
        print(f"[atp] FAILED years (network issue -- re-run to retry): {failed_years}")
    print(f"[atp] {len(engine.players)} players now have ratings")


if __name__ == "__main__":
    print(f"Starting ATP backfill from TML-Database: years {BACKFILL_YEARS[0]}-{BACKFILL_YEARS[-1]}")
    print("Source: github.com/Tennismylife/TML-Database (ATP only)")
    print("WTA is NOT covered by this script -- see comments at top of file.\n")

    backfill_atp(BACKFILL_YEARS)

    print("\nATP backfill done. Commit the updated elo_state_atp.json file")
    print("to your repo, and the next daily run will use this real history.")
