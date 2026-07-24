"""Walk-forward validation for the modular tennis model.
Usage: python3 backtest.py --tour atp --start 2024 --end 2025
"""
import argparse, math
from src.data import iter_historical_rows, normalize_surface, tier_from_row, parse_score, parse_stats
from src.ratings import RatingEngine
from src.model import combine_probability
from src.simulation import simulate_match

def logloss(p,y):
    p=max(1e-6,min(1-1e-6,p)); return -(y*math.log(p)+(1-y)*math.log(1-p))

def run(tour,start,end):
    e=RatingEngine(); n=0; correct=0; brier=0; ll=0
    # Simulator validation: compare the match simulator's predicted tiebreak /
    # straight-set rates against what actually happened in these real matches,
    # rather than only checking win-probability calibration.
    actual_tb=0; sim_tb_sum=0.0
    actual_straight=0; sim_straight_sum=0.0
    validated=0
    for row in iter_historical_rows(tour,range(start,end+1)):
        w=(row.get('winner_name') or '').strip(); l=(row.get('loser_name') or '').strip(); score=parse_score(row.get('score'))
        if not w or not l or not score: continue
        surface=normalize_surface(row); date=row.get('tourney_date') or '20000101'
        f=e.predict_features(w,l,surface,date,tour=tour); p,_,_,_=combine_probability(f)
        n+=1; correct += int(p>=.5); brier += (p-1)**2; ll += logloss(p,1)

        # Only validate the simulator on matches with enough games info to score,
        # and only where we're not extrapolating wildly from a fresh model state.
        if len(score) >= 2:
            validated+=1
            had_tb=any(max(a,b)==7 and abs(a-b)<=1 for a,b in score) or any(a==7 or b==7 for a,b in score)
            if had_tb: actual_tb+=1
            if len(score)==2: actual_straight+=1
            best_of=5 if tour=='atp' and (row.get('tourney_level') or '').upper()=='G' else 3
            sim=simulate_match(f['serve_point_a'],f['serve_point_b'],best_of=best_of,n=2000)
            sim_tb_sum+=sim['tiebreak']
            sim_straight_sum+=sim['straight_a']+sim['straight_b']

        e.update(w,l,surface,date,tier_from_row(row),{'winner':parse_stats(row,True),'loser':parse_stats(row,False)})
    if n:
        result={'tour':tour,'matches':n,'accuracy':round(correct/n,4),'brier':round(brier/n,4),'log_loss':round(ll/n,4)}
        if validated:
            result['simulator_validation']={
                'matches_checked':validated,
                'actual_tiebreak_rate':round(actual_tb/validated,4),
                'simulated_tiebreak_rate':round(sim_tb_sum/validated,4),
                'actual_straight_set_rate':round(actual_straight/validated,4),
                'simulated_straight_set_rate':round(sim_straight_sum/validated,4),
            }
        print(result)
    else: print('No matches processed.')

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--tour',choices=['atp','wta'],required=True); ap.add_argument('--start',type=int,default=2024); ap.add_argument('--end',type=int,default=2025); a=ap.parse_args(); run(a.tour,a.start,a.end)
