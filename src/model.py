from __future__ import annotations
from .ratings import RatingEngine, clamp
from .simulation import simulate_match
from datetime import datetime, timezone


def combine_probability(f):
    # Elo remains the anchor; serve/return is the main new independent signal.
    elo=f["elo_prob_a"]
    serve_edge=clamp(0.5 + 2.25*((f["serve_point_a"]-0.62) - (f["serve_point_b"]-0.62)),0.08,0.92)
    form=clamp(0.5 + 0.65*(f["form_a"]-f["form_b"]),0.08,0.92)
    fatigue=clamp(0.5 - 0.16*(f["fatigue_a"]-f["fatigue_b"]),0.08,0.92)
    injury=clamp(0.5 - 0.12*(f["injury_a"]-f["injury_b"]),0.08,0.92)
    # A conservative blend to avoid overreacting to noisy short-term data.
    p=0.40*elo + 0.32*serve_edge + 0.14*form + 0.08*fatigue + 0.06*injury
    return clamp(p,0.02,0.98), {"elo":elo,"serve_return":serve_edge,"form":form,"fatigue":fatigue,"injury":injury}


def make_prediction(engine, a, b, tournament, tour, surface, best_of, match_date):
    f=engine.predict_features(a,b,surface,match_date)
    p, components=combine_probability(f)
    # Blend the serve point matchup toward a probability consistent with the ensemble.
    # This prevents markets from being generated from a completely different model.
    implied_a_serve=clamp(f["serve_point_a"] + 0.12*(p-f["elo_prob_a"]),0.50,0.82)
    implied_b_serve=clamp(f["serve_point_b"] - 0.12*(p-f["elo_prob_a"]),0.50,0.82)
    sim=simulate_match(implied_a_serve, implied_b_serve, best_of=best_of)
    # Calibrate winner probability by simulation while retaining ensemble estimate.
    final_p=0.65*p+0.35*sim["win_a"]
    final_p=clamp(final_p,0.02,0.98)
    confidence="high" if min(f["sample_a"],f["sample_b"])>=40 else "medium" if min(f["sample_a"],f["sample_b"])>=15 else "low"
    agreement=max(components.values())-min(components.values())
    if agreement<0.12: agreement_label="high"
    elif agreement<0.25: agreement_label="medium"
    else: agreement_label="low"
    uncertainty=round(min(0.95,0.12+0.55*(1-min(f["sample_a"],f["sample_b"])/60)+0.20*agreement+0.15*max(f["injury_a"],f["injury_b"])),3)
    fair_a=1/final_p; fair_b=1/(1-final_p)
    return {"tour":tour.upper(),"tournament":tournament,"surface":surface or "unknown","player_a":a,"player_b":b,"match_time_utc":match_date,"match_winner":{"player_a_prob":round(final_p,4),"player_b_prob":round(1-final_p,4),"confidence":confidence},"set_winner":{"player_a_straight_sets_prob":round(sim["straight_a"],4),"player_b_straight_sets_prob":round(sim["straight_b"],4)},"games_total":{"average":round(sim["avg_games"],2),"median":sim["median_games"],"p10":sim["p10_games"],"p25":sim["p25_games"],"p75":sim["p75_games"],"p90":sim["p90_games"]},"tiebreak_probability":round(sim["tiebreak"],4),"fair_odds":{"player_a":round(fair_a,3),"player_b":round(fair_b,3)},"model_components":{k:round(v,4) for k,v in components.items()},"model_agreement":agreement_label,"uncertainty":uncertainty,"data_quality":{"sample_a":f["sample_a"],"sample_b":f["sample_b"],"fatigue_a":round(f["fatigue_a"],3),"fatigue_b":round(f["fatigue_b"],3),"injury_signal_a":round(f["injury_a"],3),"injury_signal_b":round(f["injury_b"],3),"serve_point_a":round(implied_a_serve,4),"serve_point_b":round(implied_b_serve,4),"score_distribution":sim["score_distribution"]},"confidence":confidence}
