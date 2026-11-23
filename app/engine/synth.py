"""Tiny numpy synthesiser. All sounds are generated from code: no samples, no third-party audio, nothing to license."""
import numpy as np
from scipy.signal import butter, sosfilt


def midi_hz(m):
    return 440.0 * 2 ** ((np.asarray(m, float) - 69) / 12)


def place(buf, idx, sig, loop=False):
    """Add sig into buf at idx. If loop, the part past the end wraps to the start (seamless loops)."""
    N = len(buf)
    idx = int(idx) % N if loop else int(idx)
    if idx < 0 or idx >= N:
        return
    n = min(len(sig), N - idx)
    buf[idx:idx + n] += sig[:n]
    if loop and len(sig) > n:
        rem = sig[n:n + N]
        buf[:len(rem)] += rem


def adsr(n, sr, a, d, s, r_len):
    """n = total samples including release tail of r_len seconds."""
    r = int(r_len * sr)
    hold = max(1, n - r)
    A, D = max(1, int(a * sr)), max(1, int(d * sr))
    env = np.empty(n, np.float32)
    A = min(A, hold)
    env[:A] = np.linspace(0, 1, A, endpoint=False)
    D = min(D, hold - A)
    if D > 0:
        env[A:A + D] = np.linspace(1, s, D, endpoint=False)
    env[A + D:hold] = s
    env[hold:] = np.linspace(s, 0, n - hold) if n > hold else 0
    return env


def saw(f, n, sr, ph0=0.0):
    ph = (f * np.arange(n) / sr + ph0) % 1.0
    return (2 * ph - 1).astype(np.float32)


def sine(f, n, sr):
    return np.sin(2 * np.pi * f * np.arange(n) / sr).astype(np.float32)


def note(kind, midi, dur_s, sr, vel=0.8):
    f = float(midi_hz(midi))
    if kind == "pad":      # 3 detuned saws, slow attack
        rel = 0.7
        n = int((dur_s + rel) * sr)
        x = (saw(f, n, sr) + saw(f * 1.004, n, sr, .3) + saw(f * .996, n, sr, .6)) / 3 + 0.5 * sine(f, n, sr)
        return x * adsr(n, sr, 0.25, 0.3, 0.8, rel) * vel
    if kind == "soft":     # soft sine pad
        rel = 0.9
        n = int((dur_s + rel) * sr)
        x = sine(f, n, sr) + 0.35 * sine(2 * f, n, sr) + 0.12 * sine(3 * f, n, sr)
        return x * adsr(n, sr, 0.35, 0.3, 0.85, rel) * vel * 0.8
    if kind == "bass":
        rel = 0.08
        n = int((dur_s + rel) * sr)
        x = sine(f, n, sr) + 0.45 * sine(2 * f, n, sr) + 0.15 * saw(f, n, sr)
        return x * adsr(n, sr, 0.008, 0.12, 0.7, rel) * vel
    if kind == "pluck":
        n = int((dur_s + 0.25) * sr)
        t = np.arange(n) / sr
        x = sine(f, n, sr) + 0.5 * sine(2 * f, n, sr) * np.exp(-6 * t) + 0.25 * sine(3 * f, n, sr) * np.exp(-9 * t)
        return (x * np.exp(-3.5 * t) * np.minimum(1, t * 600)).astype(np.float32) * vel
    # "lead_soft"
    rel = 0.25
    n = int((dur_s + rel) * sr)
    vib = 1 + 0.003 * np.sin(2 * np.pi * 5.2 * np.arange(n) / sr)
    x = (np.sin(2 * np.pi * f * np.cumsum(vib) / sr) + 0.25 * np.sin(4 * np.pi * f * np.cumsum(vib) / sr)).astype(np.float32)
    return x * adsr(n, sr, 0.04, 0.2, 0.75, rel) * vel


def kick(sr, vel=1.0):
    n = int(0.4 * sr)
    t = np.arange(n) / sr
    f = 45 + 110 * np.exp(-t * 30)
    ph = 2 * np.pi * np.cumsum(f) / sr
    return (np.sin(ph) * np.exp(-t * 9) * np.minimum(1, t * 800)).astype(np.float32) * vel


def _hp(x, sr, fc):
    return sosfilt(butter(2, fc, "hp", fs=sr, output="sos"), x).astype(np.float32)


def snare(sr, rng, vel=0.8):
    n = int(0.25 * sr)
    t = np.arange(n) / sr
    noise = _hp(rng.standard_normal(n), sr, 1200) * np.exp(-t * 22)
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 28)
    return ((0.8 * noise + 0.5 * tone) * np.minimum(1, t * 800)).astype(np.float32) * vel


def hat(sr, rng, vel=0.5, open_=False):
    n = int((0.22 if open_ else 0.05) * sr)
    t = np.arange(n) / sr
    return (_hp(rng.standard_normal(n), sr, 7000) * np.exp(-t * (14 if open_ else 80))).astype(np.float32) * vel * 0.6


def crash(sr, rng, vel=0.7):
    n = int(1.6 * sr)
    t = np.arange(n) / sr
    return (_hp(rng.standard_normal(n), sr, 4000) * np.exp(-t * 3.2)).astype(np.float32) * vel * 0.5


def lowpass(x, sr, fc):
    return sosfilt(butter(2, fc, "lp", fs=sr, output="sos"), x).astype(np.float32)
