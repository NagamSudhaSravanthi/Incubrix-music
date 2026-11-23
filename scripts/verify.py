"""python scripts/verify.py outdir  -> checks must-haves 1,2,5 numerically."""
import json
import sys
import numpy as np
import soundfile as sf
sys.path.insert(0, ".")
from app.engine.mix import lufs, true_peak_db

d = sys.argv[1]
m = json.load(open(f"{d}/music_manifest.json"))
mix, sr = sf.read(f"{d}/mix.wav")
want = m["request"]["duration_s"]
print(f"sample_rate        {sr}")
print(f"length error       {abs(len(mix)/sr - want)*1000:.4f} ms   (limit 50 ms)")
tot = np.zeros_like(mix)
for n, s in m["stems"].items():
    x, sr2 = sf.read(f"{d}/{s['file']}")
    assert len(x) == len(mix) and sr2 == sr, n
    tot += s["gain"] * x
res = 20*np.log10(np.sqrt(np.mean((mix-tot)**2)) / np.sqrt(np.mean(mix**2)) + 1e-12)
print(f"sum-of-stems resid {res:.1f} dB relative to mix")
print(f"LUFS               {lufs(mix, sr):.2f}   (target {m['loudness']['target_lufs']} +-1)")
print(f"true peak          {true_peak_db(mix, sr):.2f} dBTP (must be <= -1)")
print(f"sample peak        {np.max(np.abs(mix)):.3f}  last sample {mix[-1]:.6f}")
