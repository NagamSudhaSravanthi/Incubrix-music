"""python scripts/generate.py request.json outdir"""
import json
import sys
sys.path.insert(0, ".")
from app.engine.pipeline import generate

req = json.load(open(sys.argv[1]))
m, _ = generate(req, sys.argv[2])
print(json.dumps({k: m[k] for k in ("tempo_bpm", "key", "style", "loudness", "timings_s", "warnings")}, indent=2))
