"""One-time bootstrap of the modular model from free historical sources.
Usage: python3 backfill_models.py
"""
from src.pipeline import bootstrap, BOOTSTRAP_YEARS
for tour in ('atp','wta'):
    print(f'Bootstrapping {tour.upper()} {BOOTSTRAP_YEARS[0]}-{BOOTSTRAP_YEARS[-1]}')
    engine,count=bootstrap(tour,BOOTSTRAP_YEARS,f'model_state_{tour}.json')
    print(f'{tour.upper()}: {count} matches, {len(engine.players)} players')
