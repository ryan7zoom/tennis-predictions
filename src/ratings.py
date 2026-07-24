"""Rating and player-state engine for the modular tennis model."""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import defaultdict, deque
from datetime import date, datetime
import math

STARTING_ELO = 1500.0
BASE_K = 24.0
SURFACES = ("hard", "clay", "grass", "indoor_hard", "indoor_clay")


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def elo_expected(a, b):
    return 1.0 / (1.0 + 10 ** ((b - a) / 400.0))


def decay_weight(age_days, half_life):
    return math.exp(-math.log(2) * max(0, age_days) / half_life)


@dataclass
class MatchObservation:
    date: str
    opponent: str
    won: bool
    surface: str | None
    minutes: float | None = None
    sets: int = 0
    games: int = 0
    serve_points_won: float | None = None
    return_points_won: float | None = None
    service_games_won: float | None = None
    return_games_won: float | None = None
    first_serve_points_won: float | None = None
    second_serve_points_won: float | None = None
    aces: float | None = None
    double_faults: float | None = None
    retired: bool = False


@dataclass
class PlayerState:
    name: str
    overall_elo: float = STARTING_ELO
    surface_elo: dict = field(default_factory=lambda: {s: STARTING_ELO for s in SURFACES})
    overall_matches: int = 0
    surface_matches: dict = field(default_factory=lambda: defaultdict(int))
    recent: deque = field(default_factory=lambda: deque(maxlen=80))
    serve_points: list = field(default_factory=list)
    return_points: list = field(default_factory=list)
    first_serve_points: list = field(default_factory=list)
    second_serve_points: list = field(default_factory=list)
    service_games: list = field(default_factory=list)
    return_games: list = field(default_factory=list)
    last_match_date: str | None = None
    last_retirement_date: str | None = None
    recent_retirements: int = 0
    total_minutes_7d: float = 0.0
    total_sets_7d: int = 0
    total_games_7d: int = 0

    def _weighted_mean(self, values, today, half_life=180.0, prior=0.5, prior_weight=8.0):
        if not values:
            return prior
        num = prior * prior_weight
        den = prior_weight
        for item in values:
            try:
                d = datetime.strptime(item[0], "%Y%m%d").date()
                age = (today - d).days
            except Exception:
                age = 3650
            w = decay_weight(age, half_life)
            num += float(item[1]) * w
            den += w
        return num / den

    # Cold-start priors used when a player has little/no historical data yet.
    # ATP and WTA serve/return rates differ meaningfully on average, so a single
    # ATP-shaped prior for both tours systematically overrates WTA serve dominance
    # for thin-sample players -- exactly the case (e.g. a 14-match sample) where
    # the prior dominates the estimate.
    SERVE_PRIORS = {
        "atp": {"spp": 0.62, "sg": 0.78, "first": 0.72, "second": 0.52},
        "wta": {"spp": 0.57, "sg": 0.68, "first": 0.66, "second": 0.48},
    }
    RETURN_PRIORS = {
        "atp": {"rpp": 0.38, "rg": 0.22},
        "wta": {"rpp": 0.43, "rg": 0.32},
    }

    def serve_strength(self, today, surface=None, tour="atp"):
        # Weighted blend of point-level and game-level service performance.
        pr = self.SERVE_PRIORS.get((tour or "atp").lower(), self.SERVE_PRIORS["atp"])
        spp = self._weighted_mean(self.serve_points, today, 180, pr["spp"], 12)
        sg = self._weighted_mean(self.service_games, today, 180, pr["sg"], 12)
        first = self._weighted_mean(self.first_serve_points, today, 180, pr["first"], 10)
        second = self._weighted_mean(self.second_serve_points, today, 180, pr["second"], 10)
        base = 0.35 * spp + 0.30 * sg + 0.20 * first + 0.15 * second
        if surface and self.surface_matches.get(surface, 0) >= 8:
            # surface-specific evidence is kept in recent observations
            vals = [x for x in self.recent if x[1].get("surface") == surface and x[1].get("serve") is not None]
            if vals:
                surf = self._weighted_mean([(x[0], x[1]["serve"]) for x in vals], today, 240, base, 10)
                base = 0.65 * base + 0.35 * surf
        lo, hi = (0.45, 0.80) if (tour or "atp").lower() == "atp" else (0.40, 0.75)
        return clamp(base, lo, hi)

    def return_strength(self, today, surface=None, tour="atp"):
        pr = self.RETURN_PRIORS.get((tour or "atp").lower(), self.RETURN_PRIORS["atp"])
        rpp = self._weighted_mean(self.return_points, today, 180, pr["rpp"], 12)
        rg = self._weighted_mean(self.return_games, today, 180, pr["rg"], 12)
        base = 0.60 * rpp + 0.40 * rg
        if surface and self.surface_matches.get(surface, 0) >= 8:
            vals = [x for x in self.recent if x[1].get("surface") == surface and x[1].get("return") is not None]
            if vals:
                surf = self._weighted_mean([(x[0], x[1]["return"]) for x in vals], today, 240, base, 10)
                base = 0.65 * base + 0.35 * surf
        return clamp(base, 0.20, 0.60)

    def recent_form(self, today, surface=None):
        """Returns (form_score, has_data, n_matches). form_score is 0.5 with
        has_data=False when there is no usable recent match history -- callers
        must not treat that 0.5 as a genuine 'even form' signal."""
        vals = []
        for ds, obs in self.recent:
            if surface and obs.get("surface") not in (None, surface):
                continue
            try:
                age = (today - datetime.strptime(ds, "%Y%m%d").date()).days
            except Exception:
                age = 3650
            vals.append((obs.get("won", 0), decay_weight(age, 45)))
        if not vals:
            return 0.5, False, 0
        num = sum(v * w for v, w in vals)
        den = sum(w for _, w in vals)
        return clamp(num / den, 0.0, 1.0), True, len(vals)

    def fatigue_score(self, today):
        """Returns (score, has_data). score=0.0 with has_data=False means 'no
        recent match history to assess fatigue from', not 'confirmed fresh'."""
        # Workload is intentionally smooth rather than a hard arbitrary penalty.
        minutes = 0.0
        sets = 0
        games = 0
        has_data = False
        for ds, obs in self.recent:
            try:
                age = (today - datetime.strptime(ds, "%Y%m%d").date()).days
            except Exception:
                continue
            if age <= 7:
                has_data = True
                w = decay_weight(age, 5)
                minutes += (obs.get("minutes") or 0) * w
                sets += (obs.get("sets") or 0) * w
                games += (obs.get("games") or 0) * w
        score = 0.0
        score += clamp((minutes - 360) / 360, 0, 1) * 0.45
        score += clamp((sets - 12) / 12, 0, 1) * 0.25
        score += clamp((games - 110) / 110, 0, 1) * 0.20
        if self.last_match_date:
            try:
                rest = (today - datetime.strptime(self.last_match_date, "%Y%m%d").date()).days
                if rest <= 1:
                    score += 0.10
                    has_data = True
            except Exception:
                pass
        return clamp(score, 0, 1), has_data

    def injury_signal(self, today):
        """Returns (signal, has_data). has_data is False only when we have never
        seen this player play a match, so there is no basis for a reading at all."""
        signal = 0.0
        if self.last_retirement_date:
            try:
                age = (today - datetime.strptime(self.last_retirement_date, "%Y%m%d").date()).days
                if age <= 30:
                    signal += 0.45 * decay_weight(age, 21)
            except Exception:
                pass
        signal += min(0.35, self.recent_retirements * 0.12)
        if self.last_match_date:
            try:
                layoff = (today - datetime.strptime(self.last_match_date, "%Y%m%d").date()).days
                if 30 <= layoff <= 180:
                    signal += min(0.20, (layoff - 30) / 750)
            except Exception:
                pass
        has_data = self.last_match_date is not None
        return clamp(signal, 0, 1), has_data


class RatingEngine:
    def __init__(self):
        self.players = {}

    def player(self, name):
        if name not in self.players:
            self.players[name] = PlayerState(name)
        return self.players[name]

    def update(self, winner, loser, surface, match_date, tier="250", stats=None):
        stats = stats or {}
        w = self.player(winner); l = self.player(loser)
        mult = {"grand_slam": 1.35, "masters_1000": 1.15, "wta_1000": 1.15, "500": 1.0, "250": 0.9, "challenger": 0.85}.get(tier, 0.9)
        k = BASE_K * mult
        exp = elo_expected(w.overall_elo, l.overall_elo)
        w.overall_elo += k * (1 - exp); l.overall_elo += k * (0 - (1 - exp))
        w.overall_matches += 1; l.overall_matches += 1
        if surface in SURFACES:
            exp_s = elo_expected(w.surface_elo[surface], l.surface_elo[surface])
            w.surface_elo[surface] += k * (1 - exp_s)
            l.surface_elo[surface] += k * (0 - (1 - exp_s))
            w.surface_matches[surface] += 1; l.surface_matches[surface] += 1
        self._record(w, match_date, l.name, True, surface, stats.get("winner", {}))
        self._record(l, match_date, w.name, False, surface, stats.get("loser", {}))

    def _record(self, p, match_date, opponent, won, surface, s):
        try: d = datetime.strptime(str(match_date)[:8], "%Y%m%d").date()
        except Exception: d = date.today()
        ds = d.strftime("%Y%m%d")
        obs = {"won": int(won), "surface": surface, "minutes": s.get("minutes"), "sets": s.get("sets", 0), "games": s.get("games", 0), "serve": s.get("serve_points_won"), "return": s.get("return_points_won")}
        p.recent.append((ds, obs))
        p.last_match_date = ds
        if s.get("retired"):
            p.last_retirement_date = ds; p.recent_retirements += 1
        for attr, key in [("serve_points", "serve_points_won"), ("return_points", "return_points_won"), ("first_serve_points", "first_serve_points_won"), ("second_serve_points", "second_serve_points_won"), ("service_games", "service_games_won"), ("return_games", "return_games_won")]:
            val = s.get(key)
            if val is not None:
                getattr(p, attr).append((ds, float(val)))
                if len(getattr(p, attr)) > 300: getattr(p, attr)[:] = getattr(p, attr)[-300:]

    # Tour-level average points won on serve. ATP servers hit noticeably harder
    # than WTA on average, so a single shared baseline systematically overrates
    # WTA service dominance (and therefore overrates tiebreak/deuce-set rates).
    SERVE_BASELINE = {"atp": 0.62, "wta": 0.57}

    def predict_features(self, a_name, b_name, surface, match_date, tour="atp"):
        try: today = datetime.strptime(str(match_date)[:8], "%Y%m%d").date()
        except Exception: today = date.today()
        a = self.player(a_name); b = self.player(b_name)
        ar = a.surface_elo.get(surface, a.overall_elo) if surface in SURFACES else a.overall_elo
        br = b.surface_elo.get(surface, b.overall_elo) if surface in SURFACES else b.overall_elo
        # Thin surface samples regress to overall rating.
        if surface in SURFACES:
            aw = min(1.0, a.surface_matches.get(surface, 0) / 20.0)
            bw = min(1.0, b.surface_matches.get(surface, 0) / 20.0)
            ar = aw * ar + (1-aw) * a.overall_elo
            br = bw * br + (1-bw) * b.overall_elo
        elo_p = elo_expected(ar, br)
        serve_a = a.serve_strength(today, surface, tour); serve_b = b.serve_strength(today, surface, tour)
        ret_a = a.return_strength(today, surface, tour); ret_b = b.return_strength(today, surface, tour)
        # Serve/return matchup estimate. Baseline is tour-specific: ATP and WTA
        # have meaningfully different average points-won-on-serve rates.
        baseline = self.SERVE_BASELINE.get((tour or "atp").lower(), 0.62)
        p_a_on_serve = clamp(baseline + 0.85*(serve_a-baseline) - 0.65*(ret_b-0.38), 0.42, 0.82)
        p_b_on_serve = clamp(baseline + 0.85*(serve_b-baseline) - 0.65*(ret_a-0.38), 0.42, 0.82)
        fatigue_a, fatigue_a_has_data = a.fatigue_score(today)
        fatigue_b, fatigue_b_has_data = b.fatigue_score(today)
        injury_a, injury_a_has_data = a.injury_signal(today)
        injury_b, injury_b_has_data = b.injury_signal(today)
        form_a, form_a_has_data, form_a_n = a.recent_form(today, surface)
        form_b, form_b_has_data, form_b_n = b.recent_form(today, surface)
        return {
            "elo_prob_a": elo_p, "serve_point_a": p_a_on_serve, "serve_point_b": p_b_on_serve,
            "serve_rating_a": serve_a, "serve_rating_b": serve_b, "return_rating_a": ret_a, "return_rating_b": ret_b,
            "fatigue_a": fatigue_a, "fatigue_b": fatigue_b,
            "fatigue_a_has_data": fatigue_a_has_data, "fatigue_b_has_data": fatigue_b_has_data,
            "injury_a": injury_a, "injury_b": injury_b,
            "injury_a_has_data": injury_a_has_data, "injury_b_has_data": injury_b_has_data,
            "form_a": form_a, "form_b": form_b,
            "form_a_has_data": form_a_has_data, "form_b_has_data": form_b_has_data,
            "form_a_n": form_a_n, "form_b_n": form_b_n,
            "career_matches_a": a.overall_matches, "career_matches_b": b.overall_matches,
            "surface_matches_a": a.surface_matches.get(surface, 0) if surface in SURFACES else 0,
            "surface_matches_b": b.surface_matches.get(surface, 0) if surface in SURFACES else 0,
            # Back-compat aliases; prefer the explicit career_/surface_ fields above.
            "sample_a": a.overall_matches, "sample_b": b.overall_matches,
        }

    def to_dict(self):
        out = {}
        for name, p in self.players.items():
            out[name] = {"overall_elo": p.overall_elo, "surface_elo": p.surface_elo, "overall_matches": p.overall_matches, "surface_matches": dict(p.surface_matches), "recent": list(p.recent), "serve_points": p.serve_points[-300:], "return_points": p.return_points[-300:], "first_serve_points": p.first_serve_points[-300:], "second_serve_points": p.second_serve_points[-300:], "service_games": p.service_games[-300:], "return_games": p.return_games[-300:], "last_match_date": p.last_match_date, "last_retirement_date": p.last_retirement_date, "recent_retirements": p.recent_retirements}
        return out

    def load_dict(self, data):
        for name, d in data.items():
            p = self.player(name)
            p.overall_elo = d.get("overall_elo", STARTING_ELO); p.surface_elo.update(d.get("surface_elo", {})); p.overall_matches = d.get("overall_matches", 0); p.surface_matches.update(d.get("surface_matches", {})); p.recent = deque(d.get("recent", []), maxlen=80); p.serve_points = d.get("serve_points", []); p.return_points = d.get("return_points", []); p.first_serve_points = d.get("first_serve_points", []); p.second_serve_points = d.get("second_serve_points", []); p.service_games = d.get("service_games", []); p.return_games = d.get("return_games", []); p.last_match_date = d.get("last_match_date"); p.last_retirement_date = d.get("last_retirement_date"); p.recent_retirements = d.get("recent_retirements", 0)
