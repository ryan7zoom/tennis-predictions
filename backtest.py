"""Walk-forward validation for the modular tennis model.
Usage: python3 backtest.py --tour atp --start 2024 --end 2025
"""
import argparse, math
from src.data import iter_historical_rows, normalize_surface, tier_from_row, parse_score, parse_stats
from src.ratings import RatingEngine
from src.model import combine_probability

def logloss(p,y):
    p=max(1e-6,min(1-1e-6,p)); return -(y*math.log(p)+(1-y)*math.log(1-p))

def run(tour,start,end):
    e=RatingEngine(); n=0; correct=0; brier=0; ll=0
    for row in iter_historical_rows(tour,range(start,end+1)):
        w=(row.get('winner_name') or '').strip(); l=(row.get('loser_name') or '').strip(); score=parse_score(row.get('score'))
        if not w or not l or not score: continue
        surface=normalize_surface(row); date=row.get('tourney_date') or '20000101'
        f=e.predict_features(w,l,surface,date); p,_=combine_probability(f)
        n+=1; correct += int(p>=.5); brier += (p-1)**2; ll += logloss(p,1)
        e.update(w,l,surface,date,tier_from_row(row),{'winner':parse_stats(row,True),'loser':parse_stats(row,False)})
    if n:
        print({'tour':tour,'matches':n,'accuracy':round(correct/n,4),'brier':round(brier/n,4),'log_loss':round(ll/n,4)})
    else: print('No matches processed.')

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--tour',choices=['atp','wta'],required=True); ap.add_argument('--start',type=int,default=2024); ap.add_argument('--end',type=int,default=2025); a=ap.parse_args(); run(a.tour,a.start,a.end)
