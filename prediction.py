"""Modular tennis prediction pipeline.
Run: python3 prediction.py
Outputs: predictions.json and index.html.
"""
import json, traceback, sys
from src.pipeline import run
from src.render import render_site

if __name__ == "__main__":
    try:
        data=run(verbose=True)
        with open("predictions.json","w") as f: json.dump(data,f,indent=2)
        render_site(data,"index.html")
        print(f"Wrote predictions.json and index.html ({len(data.get('predictions',[]))} matches)")
    except Exception:
        traceback.print_exc(); sys.exit(1)
