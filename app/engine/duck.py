"""Voiceover ducking: detect speech, build a smooth gain curve, apply it to the mix. The voiceover is never included."""
import math
import os
import tempfile
import urllib.request
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .errors import EngineError

HOP_S = 0.01            # 10 ms analysis hop
MAX_BYTES = 60 * 1024 * 1024


def load_narration(src: str, sr: int, timeout_s: float = 20.0):
    """src = http(s) URL or local path. Returns mono float32 at sr."""
    path, tmp = src, None
    try:
        if src.startswith(("http://", "https://")):
            fd, tmp = tempfile.mkstemp(suffix=".audio")
            os.close(fd)
            with urllib.request.urlopen(src, timeout=timeout_s) as r, open(tmp, "wb") as f:
                n = 0
                while chunk := r.read(1 << 16):
                    n += len(chunk)
                    if n > MAX_BYTES:
                        raise EngineError("NARRATION_TOO_LARGE", "Narration file is larger than 60 MB.")
                    f.write(chunk)
            path = tmp
        x, rate = sf.read(path, dtype="float32", always_2d=True)
    except EngineError:
        raise
    except Exception as e:
        raise EngineError("NARRATION_UNREADABLE", f"Could not download or decode narration_url: {e}", retryable=False,
                          details={"source": src[:200]})
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    x = x.mean(axis=1)
    if rate != sr:
        g = math.gcd(int(rate), int(sr))
        x = resample_poly(x, sr // g, int(rate) // g).astype(np.float32)
    return x


def detect_speech(x, sr, min_gap_s=0.4, min_speech_s=0.12):
    """Energy VAD. Returns list of (start_s, end_s)."""
    hop = int(sr * HOP_S)
    n = len(x) // hop
    if n < 3:
        return []
    fr = x[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt(np.mean(fr ** 2, axis=1)) + 1e-9)
    top = np.percentile(db, 98)
    if top < -55:                                   # essentially silent file
        return []
    floor = np.percentile(db, 10)
    thr = max(floor + 10, top - 30, -55)
    sp = db > thr
    # fill short gaps (breaths, commas) so the music does not pump
    gap = int(min_gap_s / HOP_S)
    idx = np.flatnonzero(sp)
    if len(idx) == 0:
        return []
    for a, b in zip(idx[:-1], idx[1:]):
        if 1 < b - a <= gap:
            sp[a:b] = True
    segs, start = [], None
    for i, v in enumerate(sp):
        if v and start is None:
            start = i
        if not v and start is not None:
            segs.append((start, i)); start = None
    if start is not None:
        segs.append((start, n))
    return [(a * HOP_S, b * HOP_S) for a, b in segs if (b - a) * HOP_S >= min_speech_s]


def gain_curve(segs, duration_s, depth_db=12.0, attack_s=0.08, release_s=0.5, lead_s=0.1):
    """Per-10ms gain in dB: 0 normally, -depth under speech; fast attack, slow release (no pumping)."""
    n = int(math.ceil(duration_s / HOP_S)) + 1
    target = np.zeros(n)
    for a, b in segs:
        i0, i1 = max(0, int((a - lead_s) / HOP_S)), min(n, int(b / HOP_S) + 1)
        target[i0:i1] = -depth_db
    out = np.empty(n)
    ka, kr = 1 - math.exp(-HOP_S / attack_s), 1 - math.exp(-HOP_S / release_s)
    cur = 0.0
    for i in range(n):
        k = ka if target[i] < cur else kr        # going down = attack, going up = release
        cur += (target[i] - cur) * k
        out[i] = cur
    return out


def simplify(curve, step_db=0.5):
    pts, last = [], None
    for i, v in enumerate(curve):
        if last is None or abs(v - last) >= step_db or i == len(curve) - 1:
            pts.append([round(i * HOP_S, 3), round(float(v), 2)]); last = v
    return pts


def apply_ducking(mix, sr, narration, depth_db=12.0):
    """Returns (ducked_mix, info dict, warnings)."""
    warnings = []
    depth_db = float(min(15.0, max(8.0, depth_db)))
    segs = detect_speech(narration, sr)
    if not segs:
        warnings.append({"code": "NARRATION_NO_SPEECH", "message": "No speech detected in the narration; the ducked mix equals the normal mix."})
    dur = len(mix) / sr
    curve = gain_curve(segs, dur, depth_db)
    t = np.arange(len(mix)) / sr
    g = 10 ** (np.interp(t, np.arange(len(curve)) * HOP_S, curve) / 20)
    ducked = (mix * g).astype(np.float32)
    if narration is not None and len(narration) / sr > dur + 0.5:
        warnings.append({"code": "NARRATION_LONGER_THAN_MUSIC", "message": "Narration is longer than the track; speech after the end is ignored."})
    info = {"depth_db": depth_db, "attack_s": 0.08, "release_s": 0.5, "min_gap_filled_s": 0.4,
            "speech_segments_s": [[round(a, 2), round(b, 2)] for a, b in segs if a < dur],
            "gain_curve_db": simplify(curve)}
    return ducked, info, warnings
