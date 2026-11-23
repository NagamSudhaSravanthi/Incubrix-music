"""Render each instrument SEPARATELY from the plan. Stems are independent parts, never band-split copies of a mix."""
import numpy as np

from . import synth as S

STEMS = ["drums", "bass", "pads", "melody"]
BASE_GAINS = {"drums": 0.9, "bass": 0.9, "pads": 0.55, "melody": 0.6}
ROLE = {"drums": "Synthesised kick/snare/hat/crash", "bass": "Synthesised bass voice",
        "pads": "Synthesised chord pad", "melody": "Synthesised lead melody"}


def _rng(plan, name, *extra):
    # per-stem seed: changing variants[name] regenerates ONLY that stem
    return np.random.default_rng([plan.seed, STEMS.index(name), int(plan.variants.get(name, 0)), *[int(x) for x in extra]])


def _tier(e):
    return 0 if e < .2 else 1 if e < .5 else 2 if e < .8 else 3


def _t(plan, bar, step=0.0):
    return int(round((bar * plan.bar_len + step * plan.bar_len / 16) * plan.sr))


def _ring_s(plan):
    return plan.duration_s - plan.hit_bar * plan.bar_len


# ------------------------------------------------------------------ drums
def _pattern(style, e):
    t = _tier(e)
    if t == 0:
        return dict(k=[(0, .55)], s=[], h=[(i, .25) for i in (0, 4, 8, 12)], oh=[])
    if t == 1:
        return dict(k=[(0, .8), (8, .7)], s=[], h=[(i, .35) for i in range(0, 16, 2)], oh=[])
    if style == "four":
        p = dict(k=[(i, .95) for i in (0, 4, 8, 12)], s=[(4, .7), (12, .7)], h=[(i, .5) for i in (2, 6, 10, 14)], oh=[14])
    elif style in ("lofi",):
        p = dict(k=[(0, .85), (10, .7)], s=[(4, .55), (12, .6)], h=[(i, .4) for i in range(0, 16, 2)], oh=[])
    elif style == "epic":
        p = dict(k=[(0, 1.0), (8, .9)], s=[(12, .95)], h=[(i, .3) for i in range(0, 16, 4)], oh=[])
    elif style == "rock":
        p = dict(k=[(0, 1.0), (8, .9), (10, .8)], s=[(4, .95), (12, .95)], h=[(i, .55) for i in range(0, 16, 2)], oh=[14])
    elif style == "soft":
        p = dict(k=[(0, .6), (8, .5)], s=[], h=[(i, .3) for i in range(0, 16, 2)], oh=[])
    else:  # pop
        p = dict(k=[(0, .9), (8, .85)], s=[(4, .8), (12, .8)], h=[(i, .5) for i in range(0, 16, 2)], oh=[14])
    if t == 3:
        if style in ("four", "pop", "rock"):
            p["h"] = [(i, .55 if i % 2 == 0 else .3) for i in range(16)]
        p["k"] = p["k"] + ([(14, .7)] if style in ("pop", "rock") else [])
    return p


def render_drums(plan):
    sr, N = plan.sr, plan.N
    buf = np.zeros(N, np.float32)
    rng = _rng(plan, "drums")
    style = plan.preset["drums"]
    swing = style in ("lofi",)
    K = S.kick(sr)
    for b in range(plan.n_bars):
        if b == plan.hit_bar and not plan.loop:
            S.place(buf, _t(plan, b), K * 1.1)
            S.place(buf, _t(plan, b), S.crash(sr, rng, 0.9))
            S.place(buf, _t(plan, b), S.snare(sr, rng, 0.6))
            continue
        e = plan.bar_energy[b]
        p = _pattern(style, e)
        sh = lambda st: st + (0.5 if swing and st % 4 == 2 else 0)
        for st, v in p["k"]:
            S.place(buf, _t(plan, b, st), K * v, plan.loop)
        for st, v in p["s"]:
            S.place(buf, _t(plan, b, st), S.snare(sr, rng, v), plan.loop)
        for st, v in p["h"]:
            S.place(buf, _t(plan, b, sh(st)), S.hat(sr, rng, v * (0.85 + 0.3 * rng.random()), st in p["oh"]), plan.loop)
        if plan.fill_bar[b] and _tier(e) >= 1:      # snare fill on the last beat before a section change
            for i, st in enumerate(range(12, 16)):
                S.place(buf, _t(plan, b, st), S.snare(sr, rng, 0.4 + 0.15 * i), plan.loop)
        if plan.crash_bar[b] and _tier(e) >= 1:
            S.place(buf, _t(plan, b), S.crash(sr, rng, 0.6), plan.loop)
    return buf


# ------------------------------------------------------------------ bass
def render_bass(plan):
    sr, N = plan.sr, plan.N
    buf = np.zeros(N, np.float32)
    style = plan.preset["drums"]
    for b in range(plan.n_bars):
        r = 36 + plan.root_pc + plan.chord_root[b]
        if r > 47:
            r -= 12
        if b == plan.hit_bar and not plan.loop:
            S.place(buf, _t(plan, b), S.note("bass", r, _ring_s(plan) * 0.9, sr, 0.95))
            continue
        e = plan.bar_energy[b]
        t = _tier(e)
        if t == 0:
            ev = [(0, 16, 0, .55)]
        elif t == 1:
            ev = [(0, 8, 0, .8), (8, 6, 0, .7), (14, 2, 7, .6)]
        elif t == 2 and style != "four":
            ev = [(0, 4, 0, .9), (4, 4, 0, .7), (8, 4, 0, .85), (12, 2, 7, .7), (14, 2, 0, .7)]
        else:
            ev = [(i * 2, 2, 12 if i % 4 == 3 else 0, .9) for i in range(8)]
        for st, ln, off, v in ev:
            S.place(buf, _t(plan, b, st), S.note("bass", r + off, ln * plan.bar_len / 16 * 0.95, sr, v), plan.loop)
    return S.lowpass(buf, sr, 900)


# ------------------------------------------------------------------ pads
def render_pads(plan):
    sr, N = plan.sr, plan.N
    buf = np.zeros(N, np.float32)
    kind = plan.preset["pad"]
    base = 60 + plan.root_pc - 12
    for b in range(plan.n_bars):
        e = plan.bar_energy[b]
        ring = b == plan.hit_bar and not plan.loop
        dur = _ring_s(plan) * 0.95 if ring else plan.bar_len
        for off in plan.chords[b]:
            m = base + off
            S.place(buf, _t(plan, b), S.note(kind, m, dur, sr, 0.35 + 0.4 * e), plan.loop)
    return S.lowpass(buf, sr, 3500)


# ------------------------------------------------------------------ melody
def render_melody(plan):
    sr, N = plan.sr, plan.N
    buf = np.zeros(N, np.float32)
    kind = plan.preset["lead"]
    pool = [72 + plan.root_pc - 12 + s + 12 * o for o in range(2) for s in plan.scale]   # 2 octaves of the key
    for b in range(plan.n_bars):
        if b == plan.hit_bar and not plan.loop:
            S.place(buf, _t(plan, b), S.note("soft", pool[0], _ring_s(plan) * 0.9, sr, 0.7))
            continue
        e = plan.bar_energy[b]
        t = _tier(e)
        rng = _rng(plan, "melody", b % 4, t)           # same bar-in-phrase + energy tier => same phrase (repetition)
        if t == 0:
            ev = [(0, 14)]
        elif t == 1:
            ev = [(0, 4), (4, 4), (8, 8)]
        elif t == 2:
            ev = [(0, 2), (2, 2), (4, 4), (8, 2), (10, 2), (12, 4)]
        else:
            ev = [(i * 2, 2) for i in range(8)]
        tones = {(c + plan.root_pc + 60 - 12) % 12 for c in plan.chords[b]}
        idx = 4 + (b % 4) * 1
        for st, ln in ev:
            idx = int(np.clip(idx + rng.choice([-2, -1, 0, 1, 1, 2]), 1, len(pool) - 2))
            if st % 8 == 0:                              # strong beats land on chord tones
                for d in (0, 1, -1, 2, -2):
                    j = int(np.clip(idx + d, 0, len(pool) - 1))
                    if pool[j] % 12 in tones:
                        idx = j
                        break
            S.place(buf, _t(plan, b, st), S.note(kind, pool[idx], ln * plan.bar_len / 16 * 0.9, sr, 0.5 + 0.3 * e), plan.loop)
    return buf


RENDERERS = {"drums": render_drums, "bass": render_bass, "pads": render_pads, "melody": render_melody}


def render_stem(plan, name):
    x = RENDERERS[name](plan).astype(np.float32)
    if not plan.loop:                                    # on-purpose ending: final hit on the bar line, then a fade to silence
        fade = int(min(1.5, 0.75 * _ring_s(plan)) * plan.sr)
        x[-fade:] *= (0.5 * (1 + np.cos(np.linspace(0, np.pi, fade)))).astype(np.float32)
        x[-1] = 0.0
    rms = float(np.sqrt(np.mean(x ** 2))) or 1.0
    x = x * (0.12 / rms)                                 # equal loudness per stem; the balance lives in the gains
    return (np.tanh(x / 0.2) * 0.2).astype(np.float32)   # fixed per-stem soft limit: a stem never depends on the other stems


def render_stems(plan, only=None):
    return {n: render_stem(plan, n) for n in (only or STEMS)}
