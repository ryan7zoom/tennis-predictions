# Modular Tennis Predictions

A free, standard-library-only ATP/WTA tennis prediction system designed for pre-match betting analysis.

## What changed

- Replaced the old single-file Elo -> synthetic point-probability architecture with a modular package.
- Added free historical bootstrap sources:
  - ATP: Tennismylife/TML-Database season CSVs.
  - WTA: Jeff Sackmann's `tennis_wta` season CSVs.
- Added overall Elo and surface Elo with thin-sample regression.
- Added exponentially time-decayed recent form.
- Added serve and return strength ratings using historical serve/return statistics where available.
- Added opponent-aware serve-vs-return matchup inputs.
- Added a serve-specific tennis simulator that produces match, straight-set, tiebreak, and total-games distributions.
- Added fatigue/workload signals from recent matches, sets, games, and minutes where available.
- Added automated statistical injury/availability signals based on retirements and layoffs.
- Added fair decimal odds generated from model probabilities.
- Added model-component agreement and uncertainty scores.
- Added walk-forward backtesting with accuracy, Brier score, and log loss.
- Added a one-time bootstrap GitHub Action.
- Kept the daily GitHub Actions workflow and static website output.

## First-time setup

1. Replace your current `prediction.py` with the new one.
2. Add the `src/` folder.
3. Add `backfill_models.py` and `backtest.py`.
4. Replace `.github/workflows/tennis-predictions.yml` with the new workflow.
5. Add `.github/workflows/bootstrap-models.yml`.
6. Keep your existing `index.html` only as a fallback; the pipeline regenerates it.
7. Run the **Bootstrap Tennis Model** GitHub Action once.
8. After it commits `model_state_atp.json` and `model_state_wta.json`, the daily workflow will use them.

## Local run

```bash
python3 prediction.py
```

No third-party packages are required.

## Backtest

```bash
python3 backtest.py --tour atp --start 2024 --end 2025
python3 backtest.py --tour wta --start 2024 --end 2025
```

## Important

The system produces model probabilities and fair odds. It does not need bookmaker odds to operate. You can compare the model's fair odds with your bookmaker's price manually.

The historical sources are free, but respect their respective licenses and attribution requirements when redistributing data or derived datasets.
