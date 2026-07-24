"""Free data sources: ESPN for current matches; TML ATP and Sackmann WTA for historical stats."""
from __future__ import annotations
import csv, io, json, os, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

ESPN_URL="https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard"
ATP_URL="https://raw.githubusercontent.com/Tennismylife/TML-Database/master/{year}.csv"
WTA_URL="https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/wta_matches_{year}.csv"

SURFACE_MAP={"hard":"hard","clay":"clay","grass":"grass","carpet":"indoor_hard"}

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
