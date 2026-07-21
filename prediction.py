"""
prediction.py

Combined ATP/WTA tennis prediction system -- single-file build.

Modules merged into this file (in dependency order):
  1. Surface lookup table
  2. Tournament tier classifier
  3. Elo rating engine (overall + per-surface)
  4. Point-based match simulator (set-winner / games-total markets)
  5. ESPN data-fetch layer
  6. Prediction pipeline (combines Elo + simulator into one prediction per match)
  7. HTML report generator (dark-mode, 3-tab)

Run directly: python3 prediction.py
Produces predictions.json and index.html in the working directory.

Tested modules (surface lookup, tier classifier, Elo engine, match
simulator) passed 22/22 synthetic tests before merge -- see project
history. The ESPN data-fetch layer (fetch_scoreboard, fetch_match_summary,
build_elo_from_history, fetch_upcoming_matches) has NOT been verified
against the live API from this build environment (no network access to
espn.com here) -- first live GitHub Actions run is the real first test
of that piece specifically. Everything downstream of it (prediction
combination, HTML rendering) has been verified against realistic
hand-fed data.
"""

import json
import math
import random
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache


# ============================================================
# surface_lookup.py
# ============================================================
"""
Tournament -> Surface lookup table.

Design rule (non-negotiable): unmapped tournaments return None. Never guess.
A wrong silent guess corrupts surface-specific Elo for BOTH players in that match.

Surfaces used: 'hard', 'clay', 'grass', 'indoor_hard', 'indoor_clay'
Sourced from public ATP/WTA tour calendars. Surfaces are stable year to year
for a given tournament (they essentially never change), so this table does
not need a year dimension.
"""

# Grand Slams (trivial, permanent, all 4)
GRAND_SLAMS = {
    "australian open": "hard",
    "french open": "clay",
    "roland garros": "clay",
    "wimbledon": "grass",
    "us open": "hard",
}

# ATP Masters 1000 (9 events)
ATP_MASTERS_1000 = {
    "indian wells masters": "hard",
    "bnp paribas open": "hard",  # Indian Wells alt name
    "miami open": "hard",
    "monte carlo masters": "clay",
    "rolex monte-carlo masters": "clay",
    "madrid open": "clay",
    "mutua madrid open": "clay",
    "italian open": "clay",
    "internazionali bnl d'italia": "clay",
    "rome masters": "clay",
    "canadian open": "hard",
    "national bank open": "hard",
    "cincinnati open": "hard",
    "western & southern open": "hard",
    "shanghai masters": "hard",
    "rolex shanghai masters": "hard",
    "paris masters": "indoor_hard",
    "rolex paris masters": "indoor_hard",
}

# WTA 1000 (10 events)
WTA_1000 = {
    "indian wells open": "hard",
    "miami open wta": "hard",
    "madrid open wta": "clay",
    "italian open wta": "clay",
    "internazionali bnl d'italia wta": "clay",
    "canadian open wta": "hard",
    "national bank open wta": "hard",
    "cincinnati open wta": "hard",
    "wuhan open": "hard",
    "china open": "hard",
    "guadalajara open": "hard",
    "wta finals": "indoor_hard",
}

# Common 500-level events (both tours, non-exhaustive by design)
ATP_500 = {
    "rotterdam open": "indoor_hard",
    "abn amro open": "indoor_hard",
    "rio open": "clay",
    "dubai tennis championships": "hard",
    "barcelona open": "clay",
    "trofeo conde de godo": "clay",
    "queen's club championships": "grass",
    "cinch championships": "grass",
    "halle open": "grass",
    "terra wortmann open": "grass",
    "washington open": "hard",
    "china open atp": "hard",
    "japan open": "hard",
    "kinoshita group japan open": "hard",
    "vienna open": "indoor_hard",
    "erste bank open": "indoor_hard",
    "swiss indoors basel": "indoor_hard",
}

WTA_500 = {
    "qatar open": "hard",
    "dubai tennis championships wta": "hard",
    "charleston open": "clay",
    "credit one charleston open": "clay",
    "stuttgart open": "clay",
    "porsche tennis grand prix": "clay",
    "berlin open": "grass",
    "bad homburg open": "grass",
    "eastbourne open": "grass",
    "rothesay international eastbourne": "grass",
    "tokyo open": "hard",
    "toray pan pacific open": "hard",
    "korea open": "hard",
}

# Merge into one lookup, normalized to lowercase for matching
_ALL_TABLES = [GRAND_SLAMS, ATP_MASTERS_1000, WTA_1000, ATP_500, WTA_500]
SURFACE_TABLE = {}
for table in _ALL_TABLES:
    for name, surface in table.items():
        SURFACE_TABLE[name.strip().lower()] = surface

# Track lookups that missed, for the coverage-report helper
_MISSED_LOOKUPS = set()


def get_surface(tournament_name: str):
    """
    Returns surface string, or None if unmapped.
    NEVER guesses. None means: caller must treat surface as unknown.
    """
    if not tournament_name:
        _MISSED_LOOKUPS.add("<empty>")
        return None
    key = tournament_name.strip().lower()
    surface = SURFACE_TABLE.get(key)
    if surface is None:
        _MISSED_LOOKUPS.add(tournament_name)
    return surface


def surface_coverage_report():
    """
    Returns the set of tournament names that were looked up and missed.
    Call this periodically against real ESPN data to find gaps to add.
    """
    return sorted(_MISSED_LOOKUPS)


def reset_surface_coverage_tracking():
    _MISSED_LOOKUPS.clear()


def table_size():
    return len(SURFACE_TABLE)


# ============================================================
# tier_classifier.py
# ============================================================
"""
Tournament tier classifier: Grand Slam / Masters 1000 / WTA 1000 / 500 / 250.

Tier matters because it should scale the Elo K-factor -- a Slam win should
move ratings more than a 250 win.

IMPORTANT: this table currently classifies by NAME MATCH against the same
tournaments enumerated in surface_lookup.py. ESPN's raw scoreboard payload
was not available to inspect live in this session (no network access to
espn.com from this environment) -- so the "check ESPN's `major` field first"
step from the build outline has NOT been done yet. This is a real gap, not
an oversight: when the data-fetch layer is built next and can actually hit
the live ESPN endpoint, the first step should be to print the raw JSON for
one event and check if `major`, `note`, or similar fields already encode
tier info before relying solely on this manual table. Until then, unmapped
tournaments return None -- same never-guess rule as the surface table.
"""


TIER_GRAND_SLAM = "grand_slam"
TIER_MASTERS_1000 = "masters_1000"
TIER_WTA_1000 = "wta_1000"
TIER_500 = "500"
TIER_250 = "250"  # default fallback tier for tour-level events not otherwise classified

# K-factor multiplier by tier -- bigger events move ratings more.
# Base K-factor (defined in elo_engine.py) gets multiplied by this.
TIER_K_MULTIPLIER = {
    TIER_GRAND_SLAM: 1.5,
    TIER_MASTERS_1000: 1.25,
    TIER_WTA_1000: 1.25,
    TIER_500: 1.0,
    TIER_250: 0.75,
}

_TIER_TABLE = {}
for name in GRAND_SLAMS:
    _TIER_TABLE[name.strip().lower()] = TIER_GRAND_SLAM
for name in ATP_MASTERS_1000:
    _TIER_TABLE[name.strip().lower()] = TIER_MASTERS_1000
for name in WTA_1000:
    _TIER_TABLE[name.strip().lower()] = TIER_WTA_1000
for name in ATP_500:
    _TIER_TABLE[name.strip().lower()] = TIER_500
for name in WTA_500:
    _TIER_TABLE[name.strip().lower()] = TIER_500

_MISSED_TIER_LOOKUPS = set()


def get_tier(tournament_name: str):
    """
    Returns tier string, or None if unmapped (never guesses).
    Caller decides fallback behavior (e.g. default to '250' explicitly,
    which is a caller-level policy decision, not something this function
    should silently do).
    """
    if not tournament_name:
        _MISSED_TIER_LOOKUPS.add("<empty>")
        return None
    key = tournament_name.strip().lower()
    tier = _TIER_TABLE.get(key)
    if tier is None:
        _MISSED_TIER_LOOKUPS.add(tournament_name)
    return tier


def get_k_multiplier(tier: str, default: float = 0.75):
    """Given a tier (or None), return the K-factor multiplier."""
    if tier is None:
        return default
    return TIER_K_MULTIPLIER.get(tier, default)


def tier_coverage_report():
    return sorted(_MISSED_TIER_LOOKUPS)


def reset_tier_coverage_tracking():
    _MISSED_TIER_LOOKUPS.clear()


# ============================================================
# elo_engine.py
# ============================================================
"""
Elo rating engine for tennis. Each player has ONE overall rating plus
separate ratings per surface (hard, clay, grass, indoor_hard, indoor_clay).

Core rules from the build outline:
- K-factor scales by tournament tier (bigger events move ratings more)
- Confidence label (low/medium/high) required on every prediction, derived
  from how many surface-specific matches are tracked for both players
- Thin surface samples get blended toward the overall rating rather than
  trusted outright
- If surface is unknown for a match, only update overall rating -- never
  touch surface-specific rating with an unconfirmed surface
"""


BASE_K = 32
STARTING_RATING = 1500

SURFACES = ["hard", "clay", "grass", "indoor_hard", "indoor_clay"]

# Below this many tracked surface matches (for the LOWER of the two players),
# surface rating is blended toward overall rather than trusted outright.
THIN_SAMPLE_THRESHOLD = 10

# Confidence thresholds, based on min(surface_matches_a, surface_matches_b)
CONFIDENCE_HIGH_THRESHOLD = 20
CONFIDENCE_MEDIUM_THRESHOLD = 8


class Player:
    def __init__(self, name):
        self.name = name
        self.overall_rating = STARTING_RATING
        self.surface_ratings = {s: STARTING_RATING for s in SURFACES}
        self.surface_match_counts = defaultdict(int)
        self.overall_match_count = 0

    def effective_surface_rating(self, surface):
        """
        Blends surface rating toward overall rating when the sample is thin.
        Blend weight scales linearly up to THIN_SAMPLE_THRESHOLD matches,
        at which point the surface rating is trusted fully.
        """
        if surface is None or surface not in self.surface_ratings:
            return self.overall_rating
        n = self.surface_match_counts[surface]
        if n >= THIN_SAMPLE_THRESHOLD:
            return self.surface_ratings[surface]
        weight = n / THIN_SAMPLE_THRESHOLD  # 0.0 -> 1.0
        return (weight * self.surface_ratings[surface]) + ((1 - weight) * self.overall_rating)


class EloEngine:
    def __init__(self):
        self.players = {}

    def get_player(self, name):
        if name not in self.players:
            self.players[name] = Player(name)
        return self.players[name]

    @staticmethod
    def expected_score(rating_a, rating_b):
        """Standard Elo win probability formula."""
        return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

    def predict_match(self, player_a_name, player_b_name, surface=None):
        """
        Returns a dict with win probability (using blended surface rating
        if available) and a confidence label.
        """
        a = self.get_player(player_a_name)
        b = self.get_player(player_b_name)

        rating_a = a.effective_surface_rating(surface) if surface else a.overall_rating
        rating_b = b.effective_surface_rating(surface) if surface else b.overall_rating

        prob_a = self.expected_score(rating_a, rating_b)

        if surface:
            n_a = a.surface_match_counts[surface]
            n_b = b.surface_match_counts[surface]
            sample = min(n_a, n_b)
            if sample >= CONFIDENCE_HIGH_THRESHOLD:
                confidence = "high"
            elif sample >= CONFIDENCE_MEDIUM_THRESHOLD:
                confidence = "medium"
            else:
                confidence = "low"
        else:
            # No surface known at all -- can only use overall rating.
            sample = min(a.overall_match_count, b.overall_match_count)
            confidence = "medium" if sample >= CONFIDENCE_HIGH_THRESHOLD else "low"

        return {
            "player_a": player_a_name,
            "player_b": player_b_name,
            "surface": surface,
            "player_a_win_prob": round(prob_a, 4),
            "player_b_win_prob": round(1 - prob_a, 4),
            "confidence": confidence,
            "rating_a_used": round(rating_a, 1),
            "rating_b_used": round(rating_b, 1),
        }

    def update_match(self, winner_name, loser_name, surface, tier):
        """
        Updates ratings after a completed match.
        - Always updates OVERALL ratings for both players.
        - Only updates SURFACE ratings if surface is known (not None).
        - K-factor scales by tier.
        """
        winner = self.get_player(winner_name)
        loser = self.get_player(loser_name)

        k = BASE_K * get_k_multiplier(tier)

        # --- Overall rating update (always happens) ---
        expected_winner = self.expected_score(winner.overall_rating, loser.overall_rating)
        expected_loser = 1 - expected_winner
        winner.overall_rating += k * (1 - expected_winner)
        loser.overall_rating += k * (0 - expected_loser)
        winner.overall_match_count += 1
        loser.overall_match_count += 1

        # --- Surface rating update (only if surface confirmed) ---
        if surface is not None and surface in SURFACES:
            expected_winner_surf = self.expected_score(
                winner.surface_ratings[surface], loser.surface_ratings[surface]
            )
            expected_loser_surf = 1 - expected_winner_surf
            winner.surface_ratings[surface] += k * (1 - expected_winner_surf)
            loser.surface_ratings[surface] += k * (0 - expected_loser_surf)
            winner.surface_match_counts[surface] += 1
            loser.surface_match_counts[surface] += 1
        # else: surface unknown -- deliberately skip surface update to avoid
        # corrupting surface-specific data with an unconfirmed surface.

    def to_dict(self):
        """Serialize all player state to a plain dict (JSON-safe)."""
        return {
            name: {
                "overall_rating": p.overall_rating,
                "overall_match_count": p.overall_match_count,
                "surface_ratings": p.surface_ratings,
                "surface_match_counts": dict(p.surface_match_counts),
            }
            for name, p in self.players.items()
        }

    def load_dict(self, data):
        """Rebuild player state from a dict previously produced by to_dict()."""
        for name, pdata in data.items():
            player = self.get_player(name)
            player.overall_rating = pdata.get("overall_rating", STARTING_RATING)
            player.overall_match_count = pdata.get("overall_match_count", 0)
            for s in SURFACES:
                if s in pdata.get("surface_ratings", {}):
                    player.surface_ratings[s] = pdata["surface_ratings"][s]
                if s in pdata.get("surface_match_counts", {}):
                    player.surface_match_counts[s] = pdata["surface_match_counts"][s]

    def save(self, path, last_processed_date=None):
        """Write engine state to a JSON file on disk."""
        payload = {
            "last_processed_date": last_processed_date,
            "players": self.to_dict(),
        }
        with open(path, "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

    def load(self, path):
        """
        Load engine state from a JSON file on disk, if it exists.
        Returns the saved last_processed_date string (YYYYMMDD) or None
        if there was no file to load / no date recorded yet.
        """
        try:
            with open(path, "r") as f:
                payload = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        self.load_dict(payload.get("players", {}))
        return payload.get("last_processed_date")


# ============================================================
# match_simulator.py
# ============================================================
"""
Converts Elo match-win probability into set-winner and games-total
probabilities, using the standard tennis point-based Markov approach
(Barnett & Clarke 2005 school of method -- well established in tennis
analytics literature, not something invented for this project).

WHY THIS IS NEEDED (not just "more Elo"):
Elo only outputs P(win match). It has no concept of margin -- a 70%
favorite could be a dominant closer-in-straight-sets player or a
grinder who wins every set 7-6. To get set scores and games totals we
need a MARGIN signal, which comes from modeling the match at the point
level and letting standard tennis scoring rules (game -> set -> match)
determine the distribution of outcomes.

METHOD:
1. Take Elo match-win probability P(A beats B).
2. Invert it to a "point win probability on serve" for each player,
   using binary search against the deterministic game/set/match Markov
   formulas below (there is no closed-form inverse, so we search for
   the point-probability that reproduces the target match-win prob).
3. Simulate the full match-win / set-score / games-total distribution
   analytically (via recursion + Monte Carlo for the combinatorics that
   don't have a clean closed form) from that point probability.

This is deterministic math given the inputs -- not a second trained
model -- so it can be validated with synthetic data same as the Elo
engine.
"""


random.seed(42)  # reproducible synthetic tests


def game_win_prob(p_point):
    """
    Probability of winning a single game, given probability p_point of
    winning any given point on serve. Standard closed-form tennis
    scoring formula (deuce accounted for).
    """
    p = p_point
    q = 1 - p
    # Probability of winning from 40-40 (deuce) is p^2 / (p^2 + q^2)
    if p == q:
        deuce_win = 0.5
    else:
        deuce_win = (p * p) / (p * p + q * q)
    # P(win game) = sum of ways to win before deuce + P(reach deuce)*P(win from deuce)
    win_to_love = p**4
    win_to_15 = 4 * (p**4) * q
    win_to_30 = 10 * (p**4) * (q**2)
    reach_deuce = 20 * (p**3) * (q**3)
    return win_to_love + win_to_15 + win_to_30 + reach_deuce * deuce_win


def tiebreak_win_prob(p_point):
    """
    Approximation of P(win a 7-point tiebreak) given point-win prob
    p_point, via Monte Carlo (closed form exists but is unwieldy; MC is
    simpler to keep correct and is cheap at this scale).
    """
    wins = 0
    trials = 20000
    for _ in range(trials):
        a, b = 0, 0
        while True:
            if random.random() < p_point:
                a += 1
            else:
                b += 1
            if (a >= 7 or b >= 7) and abs(a - b) >= 2:
                break
        if a > b:
            wins += 1
    return wins / trials


def set_win_prob(p_game_self, p_game_opp, p_tiebreak):
    """
    Probability of winning a set, given P(win own service game),
    P(win a return game against opponent's serve), and P(win tiebreak).

    Iterative DP over game scores (0-0 up to 6-6). Player A is assumed to
    serve first in the set; server alternates each game (standard tennis).
    dp[(games_a, games_b)] = probability of reaching that score, tracked
    alongside which player serves the NEXT game (determined purely by
    parity of games played so far -- games_a + games_b -- so no separate
    server state needs to be threaded through).
    """
    # dp[(a, b)] = probability of reaching score a-b (before the next game)
    dp = {(0, 0): 1.0}

    def server_is_a_for_next_game(a, b):
        # A serves games 0, 2, 4... (0-indexed by games played so far)
        return (a + b) % 2 == 0

    prob_win_set = 0.0

    # Build up scores game by game. Cap opponent at 5 for the "6-x" win paths,
    # handle 6-5/5-6 and 6-6 specially.
    for a in range(0, 7):
        for b in range(0, 7):
            if a == 6 and b == 6:
                continue  # handled as tiebreak below, not a further game state
            if (a >= 6 or b >= 6) and abs(a - b) >= 2:
                continue  # set already over at this score, no further games from here
            if a > 6 or b > 6:
                continue
            prob_here = dp.get((a, b), 0.0)
            if prob_here == 0.0:
                continue

            server_a = server_is_a_for_next_game(a, b)
            p_a_wins_game = p_game_self if server_a else (1 - p_game_opp)

            # Player A wins this game
            new_a, new_b = a + 1, b
            if new_a == 6 and new_b <= 4:
                prob_win_set += prob_here * p_a_wins_game
            elif new_a == 7 and new_b == 5:
                prob_win_set += prob_here * p_a_wins_game
            elif new_a == 6 and new_b == 6:
                dp[(new_a, new_b)] = dp.get((new_a, new_b), 0.0) + prob_here * p_a_wins_game
            else:
                dp[(new_a, new_b)] = dp.get((new_a, new_b), 0.0) + prob_here * p_a_wins_game

            # Player B wins this game
            new_a, new_b = a, b + 1
            if new_b == 6 and new_a <= 4:
                pass  # B wins the set, contributes 0 to A's prob_win_set
            elif new_b == 7 and new_a == 5:
                pass  # B wins the set
            elif new_a == 6 and new_b == 6:
                dp[(new_a, new_b)] = dp.get((new_a, new_b), 0.0) + prob_here * (1 - p_a_wins_game)
            else:
                dp[(new_a, new_b)] = dp.get((new_a, new_b), 0.0) + prob_here * (1 - p_a_wins_game)

    # 6-6 -> tiebreak
    prob_win_set += dp.get((6, 6), 0.0) * p_tiebreak

    return prob_win_set


def match_win_prob_from_point_prob(p_point_a, best_of=3):
    """
    Given player A's point-win probability ON SERVE (symmetric simplification:
    we use the same p for both players' serve games, differentiated by who's
    serving -- see note below), compute P(A wins the match).

    SIMPLIFICATION NOTE: this treats p_point_a as A's probability of winning
    a point on A's OWN serve, and derives B's serve-point-win-prob as the
    complement structure via game_win_prob symmetry. This is the standard
    simplification used in point-based tennis models when only aggregate
    (not serve-specific) skill is available from Elo -- consistent with
    what Elo can actually supply.
    """
    p_a_serve_game = game_win_prob(p_point_a)
    p_b_serve_game = 1 - game_win_prob(1 - p_point_a)  # A's win prob on B's serve
    p_tiebreak_a = tiebreak_win_prob(p_point_a)

    p_set = set_win_prob(p_a_serve_game, p_b_serve_game, p_tiebreak_a)

    if best_of == 3:
        # Win 2-0 or 2-1
        p_2_0 = p_set ** 2
        p_2_1 = 2 * (p_set ** 2) * (1 - p_set)
        return p_2_0 + p_2_1, p_set
    else:  # best_of == 5
        p_3_0 = p_set ** 3
        p_3_1 = 3 * (p_set ** 3) * (1 - p_set)
        p_3_2 = 6 * (p_set ** 3) * ((1 - p_set) ** 2)
        return p_3_0 + p_3_1 + p_3_2, p_set


def invert_to_point_prob(target_match_win_prob, best_of=3, tol=0.001, max_iter=40):
    """
    Binary search: find the point-win-probability that reproduces the
    target match-win probability from Elo. This is the "convert Elo
    output into a point-level model input" step.
    """
    lo, hi = 0.50, 0.99
    if target_match_win_prob < 0.5:
        lo, hi = 0.01, 0.50

    for _ in range(max_iter):
        mid = (lo + hi) / 2
        match_prob, _ = match_win_prob_from_point_prob(mid, best_of=best_of)
        if abs(match_prob - target_match_win_prob) < tol:
            return mid
        if match_prob < target_match_win_prob:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def simulate_markets(elo_match_win_prob, best_of=3, n_simulations=5000):
    """
    Main entry point: given Elo's match-win probability for player A,
    returns set-winner and games-total-over/under market probabilities.

    Uses the inverted point probability, then Monte Carlo simulates full
    matches (point by point via the game/set structure) to get the games-
    total distribution, since games-total has no clean closed form.
    """
    p_point_a = invert_to_point_prob(elo_match_win_prob, best_of=best_of)

    p_a_serve_game = game_win_prob(p_point_a)
    p_b_serve_game = 1 - game_win_prob(1 - p_point_a)
    p_tiebreak_a = tiebreak_win_prob(p_point_a)

    total_games_samples = []
    a_match_wins = 0
    straight_sets_wins_a = 0
    straight_sets_wins_b = 0

    sets_to_win = 2 if best_of == 3 else 3

    for _ in range(n_simulations):
        a_sets, b_sets = 0, 0
        total_games = 0
        while a_sets < sets_to_win and b_sets < sets_to_win:
            games_a, games_b = _simulate_one_set(p_a_serve_game, p_b_serve_game, p_tiebreak_a)
            total_games += games_a + games_b
            if games_a > games_b:
                a_sets += 1
            else:
                b_sets += 1
        total_games_samples.append(total_games)
        if a_sets > b_sets:
            a_match_wins += 1
            if b_sets == 0:
                straight_sets_wins_a += 1
        else:
            if a_sets == 0:
                straight_sets_wins_b += 1

    avg_games = sum(total_games_samples) / len(total_games_samples)
    sorted_games = sorted(total_games_samples)
    median_games = sorted_games[len(sorted_games) // 2]

    return {
        "point_prob_a_on_serve": round(p_point_a, 4),
        "simulated_match_win_prob_a": round(a_match_wins / n_simulations, 4),
        "straight_sets_prob_a": round(straight_sets_wins_a / n_simulations, 4),
        "straight_sets_prob_b": round(straight_sets_wins_b / n_simulations, 4),
        "avg_total_games": round(avg_games, 2),
        "median_total_games": median_games,
        "games_total_distribution_sample_size": n_simulations,
    }


def _simulate_one_set(p_a_serve_game, p_b_serve_game, p_tiebreak_a):
    """Point-by-point (well, game-by-game) simulation of a single set."""
    games_a, games_b = 0, 0
    a_serves = True  # alternate; assume A serves first each set for simplicity
    while True:
        p_win = p_a_serve_game if a_serves else (1 - p_b_serve_game)
        if random.random() < p_win:
            games_a += 1
        else:
            games_b += 1
        a_serves = not a_serves

        if (games_a >= 6 or games_b >= 6) and abs(games_a - games_b) >= 2:
            return games_a, games_b
        if games_a == 6 and games_b == 6:
            if random.random() < p_tiebreak_a:
                return 7, 6
            else:
                return 6, 7


# ============================================================
# data_fetch.py
# ============================================================
"""
Data-fetch layer. Pulls live ESPN tennis data for ATP and WTA, runs each
match through the tier classifier + surface lookup, and feeds results
into the Elo engine chronologically.

NOTE: this module was written without live network access to espn.com
(sandboxed build environment only allows package registries). It is
built exactly to the confirmed structure from the original diagnostic
work in the build outline:
  - scoreboard "events" are whole TOURNAMENTS
  - real matches live nested in groupings[].competitions[]
  - the match-level id inside competitions[] is what summary?event=
    needs -- NOT the top-level event id
This has NOT been re-verified live in this session. First run should
be watched closely, and any structural surprises should update this
file's assumptions and get flagged back to the surface/tier tables too.
"""



SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/summary?region=us&lang=en&contentorigin=espn&event={match_id}"

TOURS = ["atp", "wta"]


_FIRST_HTTP_ERROR_PRINTED = {"done": False}


def _http_get_json(url, timeout=15, debug_label=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        label = f" [{debug_label}]" if debug_label else ""
        if not _FIRST_HTTP_ERROR_PRINTED["done"]:
            _FIRST_HTTP_ERROR_PRINTED["done"] = True
            try:
                body = e.read().decode("utf-8")[:1000]
            except Exception:
                body = "<could not read error body>"
            print("=" * 60)
            print(f"[FIRST HTTP ERROR - FULL DIAGNOSTIC]{label}")
            print(f"  Full URL requested: {url}")
            print(f"  HTTP status: {e.code}")
            print(f"  Response headers: {dict(e.headers) if e.headers else 'none'}")
            print(f"  Response body:\n{body}")
            print("=" * 60)
        else:
            print(f"  [WARN]{label} HTTP {e.code} for {url}")
        return None
    except urllib.error.URLError as e:
        label = f" [{debug_label}]" if debug_label else ""
        print(f"  [WARN]{label} fetch failed for {url}: {e}")
        return None


def fetch_scoreboard(tour, date_str=None):
    """
    date_str format: YYYYMMDD. If None, ESPN defaults to current day.
    Returns the raw scoreboard JSON, or None on failure.
    """
    url = SCOREBOARD_URL.format(tour=tour)
    if date_str:
        url += f"?dates={date_str}"
    return _http_get_json(url)


_STRUCTURE_DEBUG_PRINTED = {"done": False}


def extract_matches_from_scoreboard(scoreboard_json, tour):
    """
    Walks the tournament-level 'events' -> groupings -> competitions
    structure and yields flat match dicts with the match-level id
    (NOT the tournament-level event id).
    """
    matches = []
    if not scoreboard_json:
        return matches

    # One-time diagnostic dump: print the raw shape of the FIRST event we
    # see, so live GitHub Actions logs show us ESPN's actual current
    # structure instead of us guessing at it. This was the root cause of
    # the last failure -- the nested id assumption was never verified
    # against live data. Remove this block once the structure is confirmed
    # stable across a few runs.
    if not _STRUCTURE_DEBUG_PRINTED["done"] and scoreboard_json.get("events"):
        _STRUCTURE_DEBUG_PRINTED["done"] = True
        first_event = scoreboard_json["events"][0]
        print(f"  [DEBUG] first event top-level keys: {list(first_event.keys())}")
        print(f"  [DEBUG] first event id: {first_event.get('id')}, name: {first_event.get('name')}")
        groupings = first_event.get("groupings", [])
        print(f"  [DEBUG] groupings count: {len(groupings)}")
        if groupings:
            comps = groupings[0].get("competitions", [])
            print(f"  [DEBUG] first grouping competitions count: {len(comps)}")
            if comps:
                print(f"  [DEBUG] first competition keys: {list(comps[0].keys())}")
                print(f"  [DEBUG] first competition id: {comps[0].get('id')}")
        # Also check if competitions live directly on the event (alternate
        # structure some ESPN sports use instead of nested groupings)
        direct_comps = first_event.get("competitions", [])
        print(f"  [DEBUG] event-level (non-grouped) competitions count: {len(direct_comps)}")
        if direct_comps:
            print(f"  [DEBUG] event-level competition id: {direct_comps[0].get('id')}")

    for event in scoreboard_json.get("events", []):
        tournament_name = event.get("name", "") or event.get("shortName", "")

        # Try nested groupings[].competitions[] first (the original
        # documented structure for tennis).
        found_any = False
        for grouping in event.get("groupings", []):
            for competition in grouping.get("competitions", []):
                found_any = True
                _append_match_from_competition(matches, competition, tournament_name, tour)

        # Fallback: some ESPN responses put competitions directly on the
        # event (no groupings layer). If groupings produced nothing, try
        # this shape instead of silently returning zero matches.
        if not found_any:
            for competition in event.get("competitions", []):
                _append_match_from_competition(matches, competition, tournament_name, tour)

    return matches


def _append_match_from_competition(matches, competition, tournament_name, tour):
    match_id = competition.get("id")
    if not match_id:
        return
    competitors = competition.get("competitors", [])
    if len(competitors) != 2:
        return  # skip walkovers/byes/malformed entries

    status = competition.get("status", {}).get("type", {}).get("name", "")
    completed = competition.get("status", {}).get("type", {}).get("completed", False)

    matches.append({
        "tour": tour,
        "tournament_name": tournament_name,
        "match_id": match_id,
        "status": status,
        "completed": completed,
        "competitors_raw": competitors,
        "date": competition.get("date"),
    })


def fetch_match_summary(tour, match_id):
    url = SUMMARY_URL.format(tour=tour, match_id=match_id)
    return _http_get_json(url, debug_label=f"summary {tour}/{match_id}")


def parse_match_result(summary_json):
    """
    Extracts winner/loser names and best-of format from a match summary.
    Returns None if the match isn't in a parseable completed state.
    """
    if not summary_json:
        return None
    try:
        header = summary_json.get("header", {})
        competitions = header.get("competitions", [])
        if not competitions:
            return None
        comp = competitions[0]
        competitors = comp.get("competitors", [])
        if len(competitors) != 2:
            return None

        winner_name = None
        loser_name = None
        for c in competitors:
            athlete = c.get("athlete", {})
            name = athlete.get("displayName") or athlete.get("shortName")
            if c.get("winner") is True:
                winner_name = name
            else:
                loser_name = name

        if not winner_name or not loser_name:
            return None

        periods = comp.get("format", {}).get("regulation", {}).get("periods")
        best_of = 5 if periods == 5 else 3

        return {
            "winner": winner_name,
            "loser": loser_name,
            "best_of": best_of,
        }
    except (KeyError, IndexError, TypeError) as e:
        print(f"  [WARN] could not parse match summary: {e}")
        return None


def build_elo_from_history(engine: EloEngine, tour: str, days_back: int = 14, verbose=True,
                             max_matches: int = 500, since_date: str = None):
    """
    Walks back `days_back` days of scoreboard data for a tour, fetching
    each completed match's summary and feeding it into the Elo engine
    chronologically (oldest first, so ratings evolve correctly).

    since_date (YYYYMMDD string), if given, skips any day on or before
    that date -- used so a run with saved state only pulls NEW days
    instead of re-fetching everything from scratch. If None, walks the
    full days_back window (used for the first-ever run with no saved
    state yet).

    max_matches is a hard safety cap on individual summary fetches per
    tour per run -- protects against a run hanging for an unexpectedly
    long time if a tour has far more completed matches than assumed, or
    ESPN returns unusually large day-by-day results. If the cap is hit,
    the run stops early (partial history is still fine -- Elo doesn't
    need every match, just a reasonable recent sample) rather than
    continuing indefinitely.

    Returns (fed_count, latest_date_str) -- latest_date_str is the most
    recent day actually walked, for the caller to save as the new
    since_date for next run.
    """
    all_matches = []
    today = datetime.now(timezone.utc)
    latest_date_str = since_date

    for offset in range(days_back, -1, -1):
        day = today - timedelta(days=offset)
        date_str = day.strftime("%Y%m%d")
        if since_date is not None and date_str <= since_date:
            continue
        scoreboard = fetch_scoreboard(tour, date_str=date_str)
        latest_date_str = date_str
        if scoreboard is None:
            continue
        matches = extract_matches_from_scoreboard(scoreboard, tour)
        all_matches.extend(matches)

    if verbose:
        print(f"  [{tour}] found {len(all_matches)} raw match entries across {days_back} days")
        completed_matches = [m for m in all_matches if m["completed"]]
        print(f"  [{tour}] of those, {len(completed_matches)} are marked completed")
        if completed_matches:
            sample = completed_matches[0]
            print(f"  [{tour}] [DIAGNOSTIC] first completed match sample: "
                  f"match_id={sample['match_id']!r}, tournament={sample['tournament_name']!r}, "
                  f"status={sample['status']!r}")

    fed_count = 0
    fetched_count = 0
    for m in all_matches:
        if not m["completed"]:
            continue
        if fetched_count >= max_matches:
            if verbose:
                print(f"  [{tour}] [SAFETY CAP] hit {max_matches} match fetches, stopping early this run")
            break
        summary = fetch_match_summary(tour, m["match_id"])
        fetched_count += 1
        result = parse_match_result(summary)
        if result is None:
            continue

        surface = get_surface(m["tournament_name"])
        tier = get_tier(m["tournament_name"])

        engine.update_match(
            winner_name=result["winner"],
            loser_name=result["loser"],
            surface=surface,
            tier=tier,
        )
        fed_count += 1

    if verbose:
        print(f"  [{tour}] fed {fed_count} completed matches into Elo engine ({fetched_count} summary fetches)")

    return fed_count, latest_date_str


def fetch_upcoming_matches(tour, days_ahead=1):
    """
    Fetch today's (+ days_ahead) scheduled/live matches for market
    generation -- these are the matches we want PREDICTIONS for.
    """
    upcoming = []
    today = datetime.now(timezone.utc)
    for offset in range(0, days_ahead + 1):
        day = today + timedelta(days=offset)
        date_str = day.strftime("%Y%m%d")
        scoreboard = fetch_scoreboard(tour, date_str=date_str)
        if scoreboard is None:
            continue
        matches = extract_matches_from_scoreboard(scoreboard, tour)
        for m in matches:
            if not m["completed"]:
                upcoming.append(m)
    return upcoming


def extract_player_names(match):
    """Pulls the two player display names out of a raw scoreboard match entry."""
    names = []
    for c in match.get("competitors_raw", []):
        athlete = c.get("athlete", {})
        name = athlete.get("displayName") or athlete.get("shortName") or c.get("name")
        names.append(name)
    if len(names) != 2:
        return None
    return names[0], names[1]


# ============================================================
# run_predictions.py
# ============================================================
"""
Main pipeline: builds Elo ratings from recent history, then for every
upcoming match produces ONE combined prediction object covering match
winner, set winner (straight-sets probability), and games total --
all derived from the same underlying Elo rating, consistent with each
other by construction (they come from the same point-probability, not
three independently-guessed numbers).

Run standalone: python3 run_predictions.py
Writes predictions.json and index.html to the working directory.
"""

DAYS_OF_HISTORY = 14  # how far back to build Elo from before predicting


def build_combined_prediction(engine: EloEngine, player_a: str, player_b: str,
                                tournament_name: str, tour: str, best_of: int = 3):
    """
    THE combined prediction: one call in, one object out, covering
    match winner + set winner + games total, all internally consistent
    because they all derive from the same Elo match-win probability.
    """
    surface = get_surface(tournament_name)
    elo_pred = engine.predict_match(player_a, player_b, surface=surface)

    markets = simulate_markets(elo_pred["player_a_win_prob"], best_of=best_of, n_simulations=4000)

    return {
        "tour": tour.upper(),
        "tournament": tournament_name,
        "surface": surface if surface else "unknown",
        "player_a": player_a,
        "player_b": player_b,
        "match_winner": {
            "player_a_prob": elo_pred["player_a_win_prob"],
            "player_b_prob": elo_pred["player_b_win_prob"],
            "confidence": elo_pred["confidence"],
        },
        "set_winner": {
            "player_a_straight_sets_prob": markets["straight_sets_prob_a"],
            "player_b_straight_sets_prob": markets["straight_sets_prob_b"],
        },
        "games_total": {
            "average": markets["avg_total_games"],
            "median": markets["median_total_games"],
        },
        "confidence": elo_pred["confidence"],  # top-level, non-negotiable per outline
        "rating_a_used": elo_pred["rating_a_used"],
        "rating_b_used": elo_pred["rating_b_used"],
    }


ELO_STATE_PATH_TEMPLATE = "elo_state_{tour}.json"


def run_pipeline(verbose=True):
    engine = EloEngine()
    all_predictions = []

    for tour in TOURS:
        state_path = ELO_STATE_PATH_TEMPLATE.format(tour=tour)
        since_date = engine.load(state_path)
        if verbose:
            if since_date:
                print(f"\n=== Loaded saved Elo state for {tour.upper()} (as of {since_date}) ===")
            else:
                print(f"\n=== No saved Elo state for {tour.upper()} -- starting fresh ===")
            print(f"\n=== Building Elo history for {tour.upper()} ===")
        fed_count, latest_date = build_elo_from_history(
            engine, tour, days_back=DAYS_OF_HISTORY, verbose=verbose, since_date=since_date
        )
        # Save immediately so this tour's progress isn't lost even if a
        # later tour or step in this run fails.
        engine.save(state_path, last_processed_date=latest_date or since_date)
        if verbose:
            print(f"  [{tour}] saved Elo state to {state_path} (as of {latest_date or since_date})")

        if verbose:
            print(f"\n=== Fetching upcoming {tour.upper()} matches ===")
        upcoming = fetch_upcoming_matches(tour, days_ahead=1)
        if verbose:
            print(f"  found {len(upcoming)} upcoming/live matches")

        for match in upcoming:
            try:
                names = extract_player_names(match)
            except Exception as e:
                print(f"  [WARN] could not extract player names from match {match.get('match_id')}: {e}")
                continue
            if not names:
                continue
            player_a, player_b = names
            best_of = 5 if (match["tournament_name"].lower() in
                             {"australian open", "french open", "roland garros",
                              "wimbledon", "us open"} and tour == "atp") else 3

            try:
                pred = build_combined_prediction(
                    engine, player_a, player_b,
                    tournament_name=match["tournament_name"],
                    tour=tour,
                    best_of=best_of,
                )
                all_predictions.append(pred)
            except Exception as e:
                print(f"  [WARN] prediction failed for {player_a} vs {player_b}: {e}")

    surf_gap_report = surface_coverage_report()
    tier_gap_report = tier_coverage_report()

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "predictions": all_predictions,
        "data_quality": {
            "unmapped_tournaments_surface": surf_gap_report,
            "unmapped_tournaments_tier": tier_gap_report,
        },
    }

    with open("predictions.json", "w") as f:
        json.dump(output, f, indent=2)

    if verbose:
        print(f"\n=== Done: {len(all_predictions)} predictions written to predictions.json ===")
        if surf_gap_report:
            print(f"  [DATA GAP] {len(surf_gap_report)} tournament(s) missing from surface table: {surf_gap_report}")
        if tier_gap_report:
            print(f"  [DATA GAP] {len(tier_gap_report)} tournament(s) missing from tier table: {tier_gap_report}")

    return output


# ============================================================
# generate_html.py
# ============================================================
"""
Generates index.html from predictions.json.
Style: dark-mode, 3-tab (ATP / WTA / All), card layout per match.
Confidence label is prominent on every card -- non-negotiable per outline.
"""


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tennis Predictions</title>
<style>
  :root {{
    --bg: #0f1115;
    --card-bg: #1a1d24;
    --card-border: #2a2e38;
    --text-primary: #e8e9ec;
    --text-secondary: #9aa0ac;
    --accent: #4f9dff;
    --high: #35c46f;
    --medium: #e8b93a;
    --low: #e05a5a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg);
    color: var(--text-primary);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    margin: 0;
    padding: 20px;
  }}
  h1 {{ font-size: 1.4rem; margin-bottom: 4px; }}
  .meta {{ color: var(--text-secondary); font-size: 0.85rem; margin-bottom: 20px; }}
  .tabs {{ display: flex; gap: 8px; margin-bottom: 20px; }}
  .tab {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    color: var(--text-secondary);
    padding: 8px 16px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.9rem;
  }}
  .tab.active {{ color: var(--text-primary); border-color: var(--accent); }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }}
  .card {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 12px;
    padding: 16px;
  }}
  .card-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  .tour-badge {{ font-size: 0.7rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; }}
  .confidence {{
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 6px;
  }}
  .confidence.high {{ background: rgba(53,196,111,0.15); color: var(--high); }}
  .confidence.medium {{ background: rgba(232,185,58,0.15); color: var(--medium); }}
  .confidence.low {{ background: rgba(224,90,90,0.15); color: var(--low); }}
  .matchup {{ font-size: 1rem; font-weight: 600; margin-bottom: 4px; }}
  .tournament {{ font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 12px; }}
  .market-row {{ display: flex; justify-content: space-between; font-size: 0.85rem; padding: 4px 0; border-top: 1px solid var(--card-border); }}
  .market-label {{ color: var(--text-secondary); }}
  .market-value {{ font-weight: 600; }}
  .empty {{ color: var(--text-secondary); padding: 40px; text-align: center; }}
</style>
</head>
<body>
  <h1>Tennis Predictions</h1>
  <div class="meta">Generated {generated_at} &middot; {n_predictions} matches &middot; {n_gaps} data gap(s) flagged</div>

  <div class="tabs">
    <div class="tab active" onclick="showTab('all')" id="tab-all">All</div>
    <div class="tab" onclick="showTab('atp')" id="tab-atp">ATP</div>
    <div class="tab" onclick="showTab('wta')" id="tab-wta">WTA</div>
  </div>

  <div class="cards" id="cards-all">{cards_all}</div>
  <div class="cards" id="cards-atp" style="display:none;">{cards_atp}</div>
  <div class="cards" id="cards-wta" style="display:none;">{cards_wta}</div>

  <script>
    function showTab(tour) {{
      ['all', 'atp', 'wta'].forEach(t => {{
        document.getElementById('cards-' + t).style.display = (t === tour) ? 'grid' : 'none';
        document.getElementById('tab-' + t).classList.toggle('active', t === tour);
      }});
    }}
  </script>
</body>
</html>
"""

CARD_TEMPLATE = """
<div class="card">
  <div class="card-top">
    <span class="tour-badge">{tour} &middot; {surface}</span>
    <span class="confidence {confidence_class}">{confidence} confidence</span>
  </div>
  <div class="matchup">{player_a} vs {player_b}</div>
  <div class="tournament">{tournament}</div>
  <div class="market-row">
    <span class="market-label">Match winner</span>
    <span class="market-value">{player_a} {match_a_pct}% / {player_b} {match_b_pct}%</span>
  </div>
  <div class="market-row">
    <span class="market-label">Straight sets</span>
    <span class="market-value">{player_a} {straight_a_pct}% / {player_b} {straight_b_pct}%</span>
  </div>
  <div class="market-row">
    <span class="market-label">Games total (avg)</span>
    <span class="market-value">{games_avg}</span>
  </div>
</div>
"""


def render_card(pred):
    return CARD_TEMPLATE.format(
        tour=pred["tour"],
        surface=pred["surface"],
        confidence=pred["confidence"],
        confidence_class=pred["confidence"],
        player_a=pred["player_a"],
        player_b=pred["player_b"],
        tournament=pred["tournament"],
        match_a_pct=round(pred["match_winner"]["player_a_prob"] * 100, 1),
        match_b_pct=round(pred["match_winner"]["player_b_prob"] * 100, 1),
        straight_a_pct=round(pred["set_winner"]["player_a_straight_sets_prob"] * 100, 1),
        straight_b_pct=round(pred["set_winner"]["player_b_straight_sets_prob"] * 100, 1),
        games_avg=pred["games_total"]["average"],
    )


def generate_html(predictions_json_path="predictions.json", output_path="index.html"):
    with open(predictions_json_path) as f:
        data = json.load(f)

    predictions = data.get("predictions", [])
    atp_preds = [p for p in predictions if p["tour"] == "ATP"]
    wta_preds = [p for p in predictions if p["tour"] == "WTA"]

    cards_all = "".join(render_card(p) for p in predictions) or '<div class="empty">No matches found for this window.</div>'
    cards_atp = "".join(render_card(p) for p in atp_preds) or '<div class="empty">No ATP matches found.</div>'
    cards_wta = "".join(render_card(p) for p in wta_preds) or '<div class="empty">No WTA matches found.</div>'

    n_gaps = len(data.get("data_quality", {}).get("unmapped_tournaments_surface", [])) + \
             len(data.get("data_quality", {}).get("unmapped_tournaments_tier", []))

    html = HTML_TEMPLATE.format(
        generated_at=data.get("generated_at", ""),
        n_predictions=len(predictions),
        n_gaps=n_gaps,
        cards_all=cards_all,
        cards_atp=cards_atp,
        cards_wta=cards_wta,
    )

    with open(output_path, "w") as f:
        f.write(html)

    print(f"Wrote {output_path} ({len(predictions)} predictions)")


# ============================================================
# Combined entry point
# ============================================================
if __name__ == "__main__":
    import traceback
    import sys
    try:
        run_pipeline()
        generate_html()
    except Exception:
        print("\n[FATAL] Unhandled exception in pipeline:")
        traceback.print_exc()
        sys.exit(1)
