"""Serve-specific tennis scoring simulation."""
from __future__ import annotations
import random
from collections import Counter


def game_win_prob(p):
    q = 1-p
    deuce = 0.5 if p == 0.5 else p*p/(p*p+q*q)
    return p**4 + 4*p**4*q + 10*p**4*q*q + 20*p**3*q**3*deuce


def tb_prob(p):
    # Dynamic programming for a 7-point tiebreak with win-by-two at 6-6.
    dp={(0,0):1.0}; win=0.0
    for a in range(0,20):
        for b in range(0,20):
            prob=dp.get((a,b),0.0)
            if not prob: continue
            if max(a,b)>=7 and abs(a-b)>=2:
                if a>b: win += prob
                continue
            dp[(a+1,b)] = dp.get((a+1,b),0.0)+prob*p
            dp[(a,b+1)] = dp.get((a,b+1),0.0)+prob*(1-p)
    return win


def simulate_set(p_a_serve, p_b_serve):
    ga=game_win_prob(p_a_serve); gb=game_win_prob(p_b_serve)
    a=b=0; tb=False
    while True:
        server_a = (a+b)%2==0
        p = ga if server_a else 1-gb
        if random.random()<p: a+=1
        else: b+=1
        if (a>=6 or b>=6) and abs(a-b)>=2: return a,b,False
        if a==6 and b==6:
            tb=True
            p_tb = tb_prob(p_a_serve/(p_a_serve+p_b_serve))
            if random.random()<p_tb: return 7,6,True
            return 6,7,True


def simulate_match(p_a_serve, p_b_serve, best_of=3, n=12000, seed=42):
    random.seed(seed)
    need=best_of//2+1
    wins_a=wins_b=straight_a=straight_b=tb_matches=0
    total_games=[]; score_counts=Counter()
    for _ in range(n):
        sa=sb=0; games=0; tbs=0; sets=[]
        while sa<need and sb<need:
            a,b,tb=simulate_set(p_a_serve,p_b_serve); sets.append((a,b)); games+=a+b; tbs+=tb
            if a>b: sa+=1
            else: sb+=1
        if sa>sb: wins_a+=1
        else: wins_b+=1
        if tbs: tb_matches+=1
        if best_of==3 and sa==2 and sb==0: straight_a+=1
        if best_of==3 and sb==2 and sa==0: straight_b+=1
        total_games.append(games); score_counts[tuple(sets)] += 1
    total_games.sort()
    return {"win_a":wins_a/n,"win_b":wins_b/n,"straight_a":straight_a/n,"straight_b":straight_b/n,"tiebreak":tb_matches/n,"avg_games":sum(total_games)/n,"median_games":total_games[n//2],"p10_games":total_games[int(n*.10)],"p25_games":total_games[int(n*.25)],"p75_games":total_games[int(n*.75)],"p90_games":total_games[int(n*.90)],"score_distribution":[{"score":"-".join(f"{a}-{b}" for a,b in k),"prob":v/n} for k,v in score_counts.most_common(8)]}
