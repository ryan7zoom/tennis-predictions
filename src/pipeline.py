from __future__ import annotations
import json, os
from datetime import datetime, timezone
from .data import fetch_upcoming, iter_historical_rows, normalize_surface, tier_from_row, parse_stats, parse_score
from .ratings import RatingEngine
from .model import make_prediction

STATE_TEMPLATE="model_state_{tour}.json"
BOOTSTRAP_YEARS=list(range(2015,2027))

def save_engine(engine,path):
    with open(path,"w") as f: json.dump({"players":engine.to_dict()},f)

def load_engine(path):
    e=RatingEngine()
    try:
        with open(path) as f: e.load_dict(json.load(f).get("players",{}))
    except (FileNotFoundError,json.JSONDecodeError): pass
    return e

def bootstrap(tour, years=BOOTSTRAP_YEARS, state_path=None):
    e=RatingEngine(); count=0
    for row in iter_historical_rows(tour, years):
        winner=(row.get("winner_name") or "").strip(); loser=(row.get("loser_name") or "").strip()
        if not winner or not loser or not parse_score(row.get("score")): continue
        surface=normalize_surface(row); date=row.get("tourney_date") or "20000101"
        e.update(winner,loser,surface,date,tier_from_row(row),{"winner":parse_stats(row,True),"loser":parse_stats(row,False)})
        count+=1
    if state_path: save_engine(e,state_path)
    return e,count

def update_from_recent_espn(engine,tour,days=7):
    # ESPN scoreboard supplies result/winner data, but not reliable point stats.
    # We use it to keep Elo, form, workload and retirement signals current.
    from datetime import timedelta
    now=datetime.now(timezone.utc)
    count=0
    for i in range(days,-1,-1):
        d=(now-timedelta(days=i)).strftime("%Y%m%d")
        from .data import fetch_scoreboard, extract_matches
        for m in extract_matches(fetch_scoreboard(tour,d),tour):
            if not m["completed"]: continue
            cs=m["competitors"]
            winner=next((c.get("athlete",{}).get("displayName") for c in cs if c.get("winner") is True),None)
            loser=next((c.get("athlete",{}).get("displayName") for c in cs if c.get("winner") is not True),None)
            if winner and loser:
                engine.update(winner,loser,None,d,"250",{"winner":{"sets":0,"games":0},"loser":{"sets":0,"games":0}}); count+=1
    return count

def run(verbose=True):
    predictions=[]; quality={"historical_bootstrap":{},"errors":[]}
    for tour in ("atp","wta"):
        state=STATE_TEMPLATE.format(tour=tour)
        if os.path.exists(state):
            engine=load_engine(state)
            if verbose: print(f"[{tour}] loaded {len(engine.players)} players from {state}")
        else:
            if verbose: print(f"[{tour}] no model state; bootstrapping free historical data")
            engine,count=bootstrap(tour,state_path=state)
            quality["historical_bootstrap"][tour]=count
            if verbose: print(f"[{tour}] bootstrapped {count} matches")
        try:
            update_from_recent_espn(engine,tour,days=7)
        except Exception as e: quality["errors"].append(f"{tour} recent update: {e}")
        save_engine(engine,state)
        for m in fetch_upcoming(tour,1):
            a,b=m["players"]
            best_of=5 if tour=="atp" and m["tournament"].lower() in {"australian open","french open","roland garros","wimbledon","us open"} else 3
            # Surface is inferred conservatively from tournament name; unknown remains unknown.
            name=m["tournament"].lower()
            surface=None
            for token,s in (("wimbledon","grass"),("french open","clay"),("roland garros","clay"),("australian open","hard"),("us open","hard"),("indian wells","hard"),("miami open","hard"),("madrid","clay"),("rome","clay"),("italian open","clay"),("monte-carlo","clay"),("monte carlo","clay"),("halle","grass"),("queen","grass"),("queens","grass"),("eastbourne","grass"),("stuttgart","clay"),("charleston","clay"),("berlin","grass"),("bad homburg","grass"),("rotterdam","indoor_hard"),("vienna","indoor_hard"),("basel","indoor_hard"),("paris","indoor_hard")):
                if token in name: surface=s; break
            try: predictions.append(make_prediction(engine,a,b,m["tournament"],tour,surface,best_of,m.get("date")))
            except Exception as e: quality["errors"].append(f"{tour} {a} vs {b}: {e}")
    predictions.sort(key=lambda x:x.get("match_time_utc") or "9999")
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"predictions":predictions,"data_quality":quality}
