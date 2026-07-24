"""Free data sources: ESPN for current matches; TML ATP and Sackmann WTA for historical stats."""
from __future__ import annotations
import csv, io, json, os, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

ESPN_URL="https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard"
ATP_URL="https://raw.githubusercontent.com/Tennismylife/TML-Database/master/{year}.csv"
WTA_URL="https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/wta_matches_{year}.csv"

SURFACE_MAP={"hard":"hard","clay":"clay","grass":"grass","carpet":"indoor_hard"}

# Tournament name (lowercase substring) -> surface, for live/upcoming matches where
# no historical "surface" column exists yet. Ordered roughly by specificity; the
# first matching token wins, so longer/more specific names should precede generic ones.
TOURNAMENT_SURFACE_MAP=[
    # Grand Slams
    ("wimbledon","grass"),("french open","clay"),("roland garros","clay"),
    ("australian open","hard"),("us open","hard"),
    # Masters/WTA 1000
    ("indian wells","hard"),("miami open","hard"),("miami masters","hard"),
    ("madrid","clay"),("italian open","clay"),("internazionali","clay"),("rome","clay"),
    ("monte-carlo","clay"),("monte carlo","clay"),("canadian open","hard"),("national bank open","hard"),
    ("cincinnati","hard"),("shanghai","hard"),("paris masters","indoor_hard"),
    ("beijing","hard"),("wuhan","hard"),("guadalajara","hard"),
    # 500s / notable smaller events
    ("halle","grass"),("queen's","grass"),("queens","grass"),("eastbourne","grass"),
    ("s-hertogenbosch","grass"),("birmingham","grass"),("nottingham","grass"),("mallorca","grass"),
    ("bad homburg","grass"),("berlin","grass"),
    ("stuttgart","clay"),("charleston","clay"),("barcelona","clay"),("munich","clay"),
    ("estoril","clay"),("bastad","clay"),("hamburg","clay"),
    ("gstaad","clay"),("umag","clay"),("kitzbuhel","clay"),
    ("rio de janeiro","clay"),("rio open","clay"),("acapulco","hard"),("dubai","hard"),
    ("doha","hard"),("qatar","hard"),("rotterdam","indoor_hard"),("vienna","indoor_hard"),
    ("basel","indoor_hard"),("paris","indoor_hard"),("antwerp","indoor_hard"),
    ("tokyo","hard"),("japan open","hard"),("korea open","hard"),("seoul","hard"),
    ("washington","hard"),("dc open","hard"),("citi open","hard"),
    ("montreal","hard"),("toronto","hard"),("winston-salem","hard"),
    ("adelaide","hard"),("auckland","hard"),("hong kong","hard"),("brisbane","hard"),
    ("united cup","hard"),("atp cup","hard"),("davis cup","hard"),("billie jean king cup","hard"),
    ("prague","clay"),("livesport","clay"),("geneva","clay"),("lyon","clay"),
    ("marrakech","clay"),("houston","clay"),("santiago","clay"),("cordoba","clay"),
    ("buenos aires","clay"),("delray beach","hard"),("dallas","indoor_hard"),
    ("montpellier","indoor_hard"),("marseille","indoor_hard"),("open sud de france","indoor_hard"),
    ("cluj-napoca","clay"),("cluj","clay"),("bucharest","clay"),
    ("chennai","hard"),("pune","hard"),("newport","grass"),("mallorca open","grass"),
    ("hertogenbosch","grass"),("ilkley","grass"),
]

def surface_from_tournament_name(name):
    """Best-effort surface lookup for live/upcoming matches based on tournament name.
    Returns None (unknown) if no token matches, rather than guessing."""
    lname=(name or "").lower()
    for token,surface in TOURNAMENT_SURFACE_MAP:
        if token in lname: return surface
    return None

def http_json(url, timeout=30):
    req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read().decode())

def fetch_scoreboard(tour, date_str):
    try: return http_json(ESPN_URL.format(tour=tour)+"?dates="+date_str)
    except Exception as e: print(f"[WARN] ESPN {tour} {date_str}: {e}"); return None

def extract_matches(payload, tour):
    out=[]
    for event in (payload or {}).get("events",[]):
        tournament=event.get("name") or event.get("shortName") or "Unknown"
        comps=[]
        for grouping in event.get("groupings",[]): comps.extend(grouping.get("competitions",[]))
        if not comps: comps=event.get("competitions",[])
        for c in comps:
            cs=c.get("competitors",[])
            if len(cs)!=2 or any(x.get("type")=="team" or x.get("roster") for x in cs): continue
            names=[]
            for x in cs:
                a=x.get("athlete",{}); names.append(a.get("displayName") or a.get("shortName") or x.get("name"))
            if len(names)!=2 or not all(names): continue
            status=c.get("status",{}).get("type",{})
            out.append({"tour":tour,"tournament":tournament,"match_id":c.get("id"),"date":c.get("date"),"completed":status.get("completed",False),"players":names,"competitors":cs})
    return out

def fetch_upcoming(tour, days_ahead=1):
    out=[]; now=datetime.now(timezone.utc)
    for i in range(days_ahead+1):
        d=(now+timedelta(days=i)).strftime("%Y%m%d")
        out += [m for m in extract_matches(fetch_scoreboard(tour,d),tour) if not m["completed"]]
    return out

def parse_score(score):
    if not score or "W/O" in score.upper() or "DEF" in score.upper(): return None
    sets=[]
    for token in score.split():
        token=token.replace("RET","").replace("DEF","")
        if "-" not in token: continue
        try:
            a,b=token.split("-",1); a=int(a.split("(")[0]); b=int(b.split("(")[0]); sets.append((a,b))
        except: pass
    if not sets: return None
    return sets

def parse_stats(row, winner=True):
    p="w_" if winner else "l_"; opp="l_" if winner else "w_"
    def pct(num, den):
        try: return float(num)/float(den)
        except: return None
    return {"minutes":float(row.get("minutes") or 0) if str(row.get("minutes") or "").isdigit() else None,"sets":len(parse_score(row.get("score")) or []),"games":sum((a+b) for a,b in (parse_score(row.get("score")) or [])),"serve_points_won":pct((float(row.get(p+"1stWon") or 0)+float(row.get(p+"2ndWon") or 0)),float(row.get(p+"svpt") or 0)),"first_serve_points_won":pct(row.get(p+"1stWon"),row.get(p+"1stIn")),"second_serve_points_won":pct(row.get(p+"2ndWon"),float(row.get(p+"svpt") or 0)-float(row.get(p+"1stIn") or 0)),"service_games_won":None,"return_points_won":None,"return_games_won":None,"retired":"RET" in str(row.get("score") or "").upper()}

def iter_historical_rows(tour, years):
    for year in years:
        url=(ATP_URL if tour=="atp" else WTA_URL).format(year=year)
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req,timeout=60) as r: text=r.read().decode("utf-8",errors="replace")
            for row in csv.DictReader(io.StringIO(text)): yield row
        except Exception as e: print(f"[WARN] historical {tour} {year}: {e}")

def normalize_surface(row): return SURFACE_MAP.get((row.get("surface") or "").strip().lower())

def tier_from_row(row):
    level=(row.get("tourney_level") or "").upper()
    if level in ("G",): return "grand_slam"
    if level in ("M",): return "masters_1000"
    if level in ("A",): return "500"
    return "250"
