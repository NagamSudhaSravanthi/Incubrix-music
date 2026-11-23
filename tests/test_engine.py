"""Unit tests for the music engine: must-haves 1, 2, 3, 5 and the Advanced items, measured with real audio."""
import hashlib
import json

import numpy as np
import pytest
import soundfile as sf

from app.engine.duck import apply_ducking, detect_speech
from app.engine.errors import EngineError
from app.engine.mix import lufs, true_peak_db
from app.engine.pipeline import generate

SECS = [{"start_s": 0, "mood": "calm intro"}, {"start_s": 8, "mood": "build-up"}, {"start_s": 16, "mood": "uplifting peak"}]


def run(tmp_path, **kw):
    req = {"prompt": "warm acoustic pop", "duration_s": 24, "seed": 7, **kw}
    m, stems = generate(req, str(tmp_path))
    mix, sr = sf.read(str(tmp_path / "mix.wav"))
    return m, mix, sr


@pytest.mark.parametrize("dur", [5, 6.37, 10, 24.5])
def test_exact_length_stems_loudness_peak(tmp_path, dur):
    m, mix, sr = run(tmp_path, duration_s=dur)
    assert sr == 48000
    assert abs(len(mix) / sr - dur) < 0.05
    total = np.zeros_like(mix)
    for name, s in m["stems"].items():
        x, _ = sf.read(str(tmp_path / s["file"]))
        assert len(x) == len(mix)
        total += s["gain"] * x
    resid = 20 * np.log10(np.sqrt(np.mean((mix - total) ** 2)) / np.sqrt(np.mean(mix ** 2)) + 1e-12)
    assert resid < -80, resid
    assert abs(lufs(mix, sr) - (-16)) <= 1.0
    assert true_peak_db(mix, sr) <= -1.0
    assert np.max(np.abs(mix)) < 1.0
    assert abs(mix[-1]) < 1e-3          # ends on purpose: faded to silence, not a hard cut
    assert len(m["stems"]) >= 3


def test_stems_are_different_parts_not_bands(tmp_path):
    m, mix, sr = run(tmp_path)
    X = [sf.read(str(tmp_path / s["file"]))[0] for s in m["stems"].values()]
    C = np.corrcoef(np.array(X))
    off = np.abs(C[~np.eye(len(X), dtype=bool)])
    assert off.max() < 0.5, C       # independent parts: low correlation between any two stems


def test_deterministic_and_seed_changes_music(tmp_path):
    a = tmp_path / "a"; b = tmp_path / "b"; c = tmp_path / "c"
    for p, seed in ((a, 1), (b, 1), (c, 2)):
        generate({"prompt": "lofi chill", "duration_s": 12, "seed": seed}, str(p))
    h = lambda p: hashlib.sha256((p / "mix.wav").read_bytes()).hexdigest()
    assert h(a) == h(b)
    assert h(a) != h(c)


def test_sections_land_on_beats_and_energy_changes(tmp_path):
    m, mix, sr = run(tmp_path, sections=SECS, seed=3)
    beat = 60 / m["tempo_bpm"]
    for s in m["sections"]:
        assert abs(s["start_s"] / beat - round(s["start_s"] / beat)) < 0.01            # on a beat
        assert abs(s["start_s"] - s["requested_start_s"]) <= 0.5 * 4 * beat + 1e-6      # snapped to the nearest bar
    rms = lambda a, b: np.sqrt(np.mean(mix[int(a * sr):int(b * sr)] ** 2))
    t1, t2 = m["sections"][1]["start_s"], m["sections"][2]["start_s"]
    assert rms(t2 + 0.5, t2 + 4) > 1.15 * rms(t1 - 4, t1 - 0.5)                         # the peak is louder than the intro


def test_one_musical_piece_shared_grid(tmp_path):
    m, _, _ = run(tmp_path, tempo_bpm=100, key="D minor")
    assert m["key"] == "D minor" and m["tempo_bpm"] == 100
    assert len(m["grid"]["beat_times_s"]) == 40 and len(m["grid"]["bar_times_s"]) == 10


def test_regenerate_one_stem_leaves_others_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    base = {"prompt": "electronic house", "duration_s": 15, "seed": 5, "sections": SECS}
    generate(base, str(a))
    generate({**base, "variants": {"drums": 1}}, str(b))
    h = lambda p, n: hashlib.sha256((p / "stems" / f"{n}.wav").read_bytes()).hexdigest()
    for n in ("bass", "pads", "melody"):
        assert h(a, n) == h(b, n), n
    assert h(a, "drums") != h(b, "drums")


def test_loop_is_seamless(tmp_path):
    m, mix, sr = run(tmp_path, loopable=True, duration_s=16)
    bars = m["grid"]["n_bars"]
    assert abs(bars * m["grid"]["bar_len_s"] - 16) < 1e-3                     # whole number of bars
    d = np.abs(np.diff(mix))
    seam = abs(mix[0] - mix[-1])
    assert seam < 5 * np.percentile(d, 99.5) + 1e-4                            # no click at the loop point
    assert "loop" in m["ending"]


def narration(segs, total=30, sr=48000):
    x = np.zeros(int(total * sr), np.float32)
    t0 = np.random.default_rng(1)
    for a, b in segs:
        n = int((b - a) * sr); t = np.arange(n) / sr
        x[int(a * sr):int(a * sr) + n] = (np.sin(2 * np.pi * 180 * t) + 0.15 * t0.standard_normal(n)) * (0.5 + 0.5 * np.abs(np.sin(6 * np.pi * t))) * 0.3
    return x


def test_ducking_depth_and_recovery(tmp_path):
    m, mix, sr = run(tmp_path, duration_s=30)
    nar = narration([(3, 8), (8.2, 12), (22, 26)])
    ducked, info, _ = apply_ducking(mix, sr, nar, 12.0)
    rms = lambda x, a, b: 20 * np.log10(np.sqrt(np.mean(x[int(a * sr):int(b * sr)] ** 2)))
    for a, b in ((4, 7), (9, 11), (23, 25)):
        assert 8 <= rms(mix, a, b) - rms(ducked, a, b) <= 15
    assert abs(rms(mix, 14, 20) - rms(ducked, 14, 20)) < 0.1                   # music is back to full level in the gap
    assert [3.0, 12.0] == info["speech_segments_s"][0]                         # the 0.2 s breath did not split the speech
    assert max(abs(np.diff(info["gain_curve_db"], axis=0)[:, 1])) < 12         # smooth steps


def test_ducking_no_speech(tmp_path):
    m, mix, sr = run(tmp_path, duration_s=10)
    ducked, info, w = apply_ducking(mix, sr, np.zeros(sr * 5, np.float32), 12)
    assert np.allclose(ducked, mix) and w[0]["code"] == "NARRATION_NO_SPEECH"


# ---------------------------------------------------------------- hard cases
def codes(m):
    return {w["code"] for w in m["warnings"]}


def test_hard_cases_warn_instead_of_failing(tmp_path):
    cases = {
        "contradictory": (dict(prompt="calm but aggressive"), "CONTRADICTORY_PROMPT"),
        "artist": (dict(prompt="exactly like Taylor Swift with vocals"), "ARTIST_REFERENCE_IGNORED"),
        "vocals": (dict(prompt="pop song with singing and lyrics"), "VOCALS_NOT_SUPPORTED"),
        "close": (dict(sections=[{"start_s": 0, "mood": "calm"}, {"start_s": 1.0, "mood": "peak"}]), "SECTION_TOO_CLOSE"),
        "late": (dict(sections=[{"start_s": 0, "mood": "calm"}, {"start_s": 99, "mood": "peak"}]), "SECTION_AFTER_END"),
        "spanish": (dict(prompt="música tranquila y relajante"), "NON_ENGLISH_PROMPT"),
        "hindi": (dict(prompt="शांत और आरामदायक संगीत"), "NON_ENGLISH_PROMPT"),
        "vague": (dict(prompt="xyzzy"), "VAGUE_PROMPT"),
    }
    for name, (kw, code) in cases.items():
        m, mix, sr = run(tmp_path / name, **{"duration_s": 12, **kw})
        assert code in codes(m), (name, m["warnings"])
        assert abs(len(mix) / sr - 12) < 0.05


@pytest.mark.parametrize("d", [4.9, 301, "10", None])
def test_invalid_duration_is_a_clean_error(tmp_path, d):
    with pytest.raises(EngineError) as e:
        generate({"prompt": "x", "duration_s": d}, str(tmp_path))
    assert e.value.code == "INVALID_DURATION"


def test_ten_distinct_prompts_pick_ten_styles(tmp_path):
    prompts = ["cinematic epic trailer", "lofi chill study beats", "corporate presentation", "electronic house club",
               "acoustic folk guitar", "tense thriller suspense", "playful quirky kids", "ambient meditation spa",
               "rock punk driving", "smooth jazz lounge"]
    styles = set()
    for i, p in enumerate(prompts):
        m, _, _ = run(tmp_path / str(i), prompt=p, duration_s=8)
        styles.add(m["style"])
    assert len(styles) == 10
