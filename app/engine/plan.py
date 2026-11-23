"""Request -> musical plan: bar grid, key, sections, per-bar energy. Everything is planned in bars so lengths are exact."""
import math
import re
from dataclasses import dataclass, field

from .prompt import SCALES, STYLES, energy_of, has_ramp, parse_prompt

SR_DEFAULT = 48000
MIN_SECTION_GAP_S = 1.5
NOTE_PC = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


@dataclass
class Plan:
    duration_s: float
    sr: int
    seed: int
    style: str
    preset: dict
    bpm: float
    bar_len: float
    n_bars: int
    hit_bar: int
    loop: bool
    root_pc: int
    mode: str
    scale: list
    key_name: str
    chords: list            # per bar: list of 3 semitone offsets from root (triad)
    chord_root: list        # per bar: semitone offset of chord root
    bar_energy: list
    sections: list          # applied sections
    fill_bar: list
    crash_bar: list
    variants: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    @property
    def N(self):
        return int(round(self.duration_s * self.sr))


def parse_key(key, default_root, default_mode):
    if not key:
        return NOTE_PC[default_root.lower()], default_mode, False
    m = re.match(r"^\s*([A-Ga-g])([#b]?)\s*(major|minor|maj|min|m|dorian)?\s*$", str(key))
    if not m:
        return NOTE_PC[default_root.lower()], default_mode, "bad"
    pc = NOTE_PC[m.group(1).lower()] + (1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0)
    mode = (m.group(3) or "major").lower()
    mode = {"maj": "major", "min": "minor", "m": "minor"}.get(mode, mode)
    if m.group(1).islower() and not m.group(3):
        mode = "minor"
    return pc % 12, mode, True


def build_plan(req: dict) -> Plan:
    warnings = []
    duration = float(req["duration_s"])
    sr = int(req.get("output", {}).get("sample_rate", SR_DEFAULT))
    seed = int(req.get("seed") if req.get("seed") is not None else 0)
    loop = bool(req.get("loopable", False))

    pp = parse_prompt(req.get("prompt", ""))
    warnings += pp["warnings"]
    preset, style = pp["preset"], pp["style"]

    # ---- key
    root_pc, mode, ok = parse_key(req.get("key"), preset["key"], preset["scale"])
    if ok == "bad":
        warnings.append({"code": "KEY_NOT_UNDERSTOOD", "message": f"Key '{req.get('key')}' not understood; used the style default."})
    scale = SCALES[mode]
    key_name = f"{'C C# D D# E F F# G G# A A# B'.split()[root_pc]} {mode}"

    # ---- tempo and bar grid (planned in bars so the length is exact)
    fixed = req.get("tempo_bpm")
    if fixed:
        bpm0 = min(220.0, max(40.0, float(fixed)))
        if bpm0 != float(fixed):
            warnings.append({"code": "TEMPO_CLAMPED", "message": f"tempo_bpm clamped to {bpm0}."})
    else:
        lo, hi = preset["bpm"]
        bpm0 = (lo + hi) / 2 + ((seed % 5) - 2) * 2
    if fixed and not loop:
        bar_len = 240.0 / bpm0
        n_bars = max(2, int(math.floor(duration / bar_len + 1e-9)))
        bpm = bpm0
        if abs(n_bars * bar_len - duration) > 1e-6:
            warnings.append({"code": "TEMPO_FIXED_TAIL", "message": "With a fixed tempo the length is not a whole number of bars; the final chord rings out to the exact end."})
    else:
        n_bars = max(2, round(duration * bpm0 / 240.0))
        bpm = n_bars * 240.0 / duration
        if fixed:
            warnings.append({"code": "TEMPO_ADJUSTED_FOR_LOOP", "message": f"tempo_bpm {fixed} adjusted to {bpm:.2f} so the loop is a whole number of bars."})
        elif abs(bpm - bpm0) / bpm0 > 0.12:
            warnings.append({"code": "TEMPO_ADJUSTED", "message": f"Tempo set to {bpm:.1f} BPM so the bars fill {duration}s exactly."})
        bar_len = 240.0 / bpm
    hit_bar = n_bars - 1

    # ---- sections: snap to bar lines (= on a beat), drop/merge bad ones
    raw = req.get("sections") or []
    secs = []
    for s in sorted(raw, key=lambda x: float(x["start_s"])):
        st = float(s["start_s"])
        mood = s.get("mood", "")
        if st < 0:
            warnings.append({"code": "SECTION_NEGATIVE_START", "message": f"Section '{mood}' had a negative start; ignored."})
            continue
        if st >= duration:
            warnings.append({"code": "SECTION_AFTER_END", "message": f"Section '{mood}' starts at {st}s, after the end ({duration}s); ignored."})
            continue
        b = int(round(st / bar_len))
        if b >= n_bars:
            warnings.append({"code": "SECTION_AFTER_END", "message": f"Section '{mood}' at {st}s falls in the ending bar; ignored."})
            continue
        if secs and (st - secs[-1]["requested_start_s"] < MIN_SECTION_GAP_S or b <= secs[-1]["start_bar"]):
            warnings.append({"code": "SECTION_TOO_CLOSE", "message": f"Section '{mood}' at {st}s is less than {MIN_SECTION_GAP_S}s after the previous one (or snaps to the same bar); merged into it."})
            continue
        secs.append(dict(requested_start_s=st, mood=mood, start_bar=b, start_s=round(b * bar_len, 4),
                         energy=energy_of(mood, pp["energy"]), ramp=has_ramp(mood)))
    if not secs or secs[0]["start_bar"] != 0:
        secs.insert(0, dict(requested_start_s=0.0, mood="(default)", start_bar=0, start_s=0.0,
                            energy=pp["energy"], ramp=pp["ramp"]))
        if raw and len(secs) > 1:
            warnings.append({"code": "SECTION_ZERO_ADDED", "message": "No section started at 0; a default opening section was added."})
    for i, s in enumerate(secs):
        s["end_bar"] = secs[i + 1]["start_bar"] if i + 1 < len(secs) else n_bars

    # ---- per-bar energy (ramps interpolate from the previous section's level)
    bar_energy = [0.6] * n_bars
    prev = secs[0]["energy"] * 0.6
    for s in secs:
        L = s["end_bar"] - s["start_bar"]
        for k, b in enumerate(range(s["start_bar"], s["end_bar"])):
            bar_energy[b] = prev + (s["energy"] - prev) * (k + 1) / L if s["ramp"] else s["energy"]
        prev = s["energy"]
    fill_bar = [False] * n_bars
    crash_bar = [False] * n_bars
    for i, s in enumerate(secs):
        if i + 1 < len(secs) and s["end_bar"] - s["start_bar"] >= 1:
            fill_bar[s["end_bar"] - 1] = True
        before = secs[i - 1]["energy"] if i else 0
        if s["energy"] > before + 0.15 or i == 0:
            crash_bar[s["start_bar"]] = True

    # ---- chords: one triad per bar, diatonic
    def deg(d):
        return scale[d % 7] + 12 * (d // 7)
    chords, roots = [], []
    for b in range(n_bars):
        d = preset["prog"][b % len(preset["prog"])]
        roots.append(deg(d) % 12)
        chords.append([deg(d), deg(d + 2), deg(d + 4)])
    # first and last bar resolve to the tonic
    chords[hit_bar], roots[hit_bar] = [0, scale[2], 7], 0

    return Plan(duration_s=duration, sr=sr, seed=seed, style=style, preset=preset, bpm=bpm, bar_len=bar_len,
                n_bars=n_bars, hit_bar=hit_bar, loop=loop, root_pc=root_pc, mode=mode, scale=scale, key_name=key_name,
                chords=chords, chord_root=roots, bar_energy=bar_energy, sections=secs, fill_bar=fill_bar,
                crash_bar=crash_bar, variants=dict(req.get("variants") or {}), warnings=warnings)
