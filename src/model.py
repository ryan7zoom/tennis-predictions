from __future__ import annotations
from .ratings import RatingEngine, clamp
from .simulation import simulate_match
from datetime import datetime, timezone

# Base ensemble weights when every component has real data to work with.
BASE_WEIGHTS = {"elo": 0.40, "serve_return": 0.32, "form": 0.14, "fatigue": 0.08, "injury": 0.06}


def combine_probability(f):
    # Elo remains the anchor; serve/return is the main new independent signal.
    elo = f["elo_prob_a"]
    serve_edge = clamp(0.5 + 2.25*((f["serve_point_a"]-0.62) - (f["serve_point_b"]-0.62)), 0.08, 0.92)
    form = clamp(0.5 + 0.65*(f["form_a"]-f["form_b"]), 0.08, 0.92)
    fatigue = clamp(0.5 - 0.16*(f["fatigue_a"]-f["fatigue_b"]), 0.08, 0.92)
    injury = clamp(0.5 - 0.12*(f["injury_a"]-f["injury_b"]), 0.08, 0.92)

    components = {"elo": elo, "serve_return": serve_edge, "form": form, "fatigue": fatigue, "injury": injury}
    # A component with no usable data for either player is not a real opinion --
    # it's a hardcoded neutral value. Zero its ensemble weight and let elo (which
    # always has a value, even if just the starting rating) absorb the difference,
    # rather than letting several "no data" 0.5s silently outvote a real signal.
    has_data = {
        "elo": True,  # elo always has at least a starting rating
        "serve_return": True,  # serve/return ratings always compute from priors, never a bare default
        "form": f.get("form_a_has_data", True) or f.get("form_b_has_data", True),
        "fatigue": f.get("fatigue_a_has_data", True) or f.get("fatigue_b_has_data", True),
        "injury": f.get("injury_a_has_data", True) or f.get("injury_b_has_data", True),
    }
    weights = {k: (BASE_WEIGHTS[k] if has_data[k] else 0.0) for k in BASE_WEIGHTS}
    total_w = sum(weights.values()) or 1.0
    weights = {k: w/total_w for k, w in weights.items()}

    p = sum(weights[k]*components[k] for k in components)
    return clamp(p, 0.02, 0.98), components, has_data, weights


def make_prediction(engine, a, b, tournament, tour, surface, best_of, match_date):
    f = engine.predict_features(a, b, surface, match_date, tour=tour)
    p, components, has_data, weights = combine_probability(f)

    # Blend the serve point matchup toward a probability consistent with the ensemble.
    # This prevents markets from being generated from a completely different model.
    implied_a_serve = clamp(f["serve_point_a"] + 0.12*(p-f["elo_prob_a"]), 0.42, 0.82)
    implied_b_serve = clamp(f["serve_point_b"] - 0.12*(p-f["elo_prob_a"]), 0.42, 0.82)
    sim = simulate_match(implied_a_serve, implied_b_serve, best_of=best_of)

    # Calibrate winner probability by simulation while retaining ensemble estimate.
    final_p = 0.65*p + 0.35*sim["win_a"]
    final_p = clamp(final_p, 0.02, 0.98)

    # Confidence and uncertainty should reflect the data that's actually relevant
    # to this matchup: surface-specific sample size when we know the surface,
    # falling back to career sample size when we don't.
    if surface and min(f["surface_matches_a"], f["surface_matches_b"]) > 0:
        rel_sample_a, rel_sample_b = f["surface_matches_a"], f["surface_matches_b"]
    else:
        rel_sample_a, rel_sample_b = f["career_matches_a"], f["career_matches_b"]
    rel_sample = min(rel_sample_a, rel_sample_b)
    confidence = "high" if rel_sample >= 40 else "medium" if rel_sample >= 15 else "low"

    # Agreement is only meaningful across components that actually have data --
    # several "no data" 0.5s bunched together shouldn't read as "high agreement".
    active_vals = [v for k, v in components.items() if has_data[k]]
    n_active = len(active_vals)
    agreement_spread = (max(active_vals)-min(active_vals)) if active_vals else 0.0
    if n_active <= 1:
        agreement_label = "low"  # can't agree with yourself; too little signal to call it agreement
    elif agreement_spread < 0.12:
        agreement_label = "high"
    elif agreement_spread < 0.25:
        agreement_label = "medium"
    else:
        agreement_label = "low"

    uncertainty = round(clamp(0.12 + 0.55*(1-rel_sample/60) + 0.20*agreement_spread + 0.15*max(f["injury_a"], f["injury_b"]), 0.02, 0.95), 3)
    fair_a = 1/final_p
    fair_b = 1/(1-final_p)

    # Structured score distribution: explicit winner and per-set scores instead
    # of an ambiguous "7-6-7-6" string the front end has to parse and guess from.
    score_distribution = []
    for entry in sim["score_distribution"]:
        sets_a, sets_b = entry["sets_won"]
        winner = a if sets_a > sets_b else b
        score_distribution.append({
            "winner": winner,
            "sets": entry["set_scores"],
            "probability": round(entry["prob"], 4),
        })

    return {
        "tour": tour.upper(), "tournament": tournament, "surface": surface or "unknown",
        "player_a": a, "player_b": b, "match_time_utc": match_date,
        "match_winner": {"player_a_prob": round(final_p, 4), "player_b_prob": round(1-final_p, 4), "confidence": confidence},
        "set_winner": {"player_a_straight_sets_prob": round(sim["straight_a"], 4), "player_b_straight_sets_prob": round(sim["straight_b"], 4)},
        "games_total": {"average": round(sim["avg_games"], 2), "median": sim["median_games"], "p10": sim["p10_games"], "p25": sim["p25_games"], "p75": sim["p75_games"], "p90": sim["p90_games"]},
        "tiebreak_probability": round(sim["tiebreak"], 4),
        "fair_odds": {"player_a": round(fair_a, 3), "player_b": round(fair_b, 3)},
        "model_components": {
            k: {"player_a": round(v, 4), "player_b": round(1-v, 4), "weight": round(weights[k], 3), "has_data": has_data[k]}
            for k, v in components.items()
        },
        "model_agreement": agreement_label,
        "uncertainty": uncertainty,
        "data_quality": {
            "surface_known": surface is not None,
            "career_matches_a": f["career_matches_a"], "career_matches_b": f["career_matches_b"],
            "surface_matches_a": f["surface_matches_a"], "surface_matches_b": f["surface_matches_b"],
            "form_recent_matches_a": f["form_a_n"], "form_recent_matches_b": f["form_b_n"],
            "fatigue_a": round(f["fatigue_a"], 3), "fatigue_b": round(f["fatigue_b"], 3),
            "injury_signal_a": round(f["injury_a"], 3), "injury_signal_b": round(f["injury_b"], 3),
            "serve_point_a": round(implied_a_serve, 4), "serve_point_b": round(implied_b_serve, 4),
        },
        "score_distribution": score_distribution,
        "confidence": confidence,
    }
