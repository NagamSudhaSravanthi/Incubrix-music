"""Mix = sum(gain_i * stem_i), exactly. Loudness is set by the gains, so the manifest gains reproduce the mix."""
import numpy as np
import pyloudnorm as pyln
from scipy.signal import resample_poly


def lufs(x, sr):
    return float(pyln.Meter(sr).integrated_loudness(x.astype(np.float64)))


def true_peak_db(x, sr):
    up = resample_poly(x.astype(np.float64), 4, 1)
    return float(20 * np.log10(max(np.max(np.abs(up)), 1e-9)))


def summed(stems, gains):
    out = None
    for n, s in stems.items():
        out = gains[n] * s if out is None else out + gains[n] * s
    return out.astype(np.float32)


def soft_limit(x, thr):
    """Gentle tanh limiter applied to a STEM (before summing), so the sum identity still holds."""
    return (np.tanh(x / thr) * thr).astype(np.float32)


def make_mix(stems, base_gains, sr, target_lufs=-16.0, tp_ceiling=-1.0):
    warnings = []
    stems = dict(stems)
    names = list(stems)
    base = {n: base_gains.get(n, 0.7) for n in names}
    for rnd in range(4):
        L0 = lufs(summed(stems, base), sr)
        for drop in (0.0, 0.25, 0.5, 0.75, 0.9):          # may trade up to 0.9 LU (< 1 LU tolerance) for true peak
            G = 10 ** ((target_lufs - drop - L0) / 20)
            gains = {n: base[n] * G for n in names}
            mix = summed(stems, gains)
            tp = true_peak_db(mix, sr)
            if tp <= tp_ceiling - 0.1:
                if drop:
                    warnings.append({"code": "LOUDNESS_TRADEOFF", "message": f"Loudness lowered by {drop} LU to keep true peak under {tp_ceiling} dBTP."})
                return stems, gains, mix, warnings
        # still too peaky: soft-limit the stem with the highest peak and retry
        loudest = max(names, key=lambda n: float(np.max(np.abs(stems[n]))) * base[n])
        stems[loudest] = soft_limit(stems[loudest], 0.5 * float(np.max(np.abs(stems[loudest]))))
        warnings.append({"code": "STEM_SOFT_LIMITED", "message": f"Stem '{loudest}' was soft-limited to meet the true-peak ceiling."})
    return stems, gains, mix, warnings
