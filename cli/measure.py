"""Metrics benchmark script for the Metrics tab.

Run:
  python measure.py --out metrics_report.json
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time

import numpy as np
import soundfile as sf

from app.engine.errors import EngineError
from app.engine.mix import lufs, true_peak_db
from app.engine.pipeline import generate
from app.engine.render import STEMS


def measure_all() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        # 1. Standard 30s generation benchmark
        out_std = os.path.join(tmp, "std")
        req_std = {"prompt": "calm corporate background with subtle energy rise", "duration_s": 30, "seed": 7}
        t0 = time.perf_counter()
        manifest, stems = generate(req_std, out_std)
        gen_time_s = round(time.perf_counter() - t0, 4)

        mix, sr = sf.read(os.path.join(out_std, "mix.wav"), dtype="float32")
        expected_samples = int(req_std["duration_s"] * sr)
        length_error_ms = round(abs(len(mix) - expected_samples) / sr * 1000.0, 4)

        # Sum-of-stems residual check
        reconstructed = np.zeros_like(mix)
        for name in STEMS:
            gain = manifest["stems"][name]["gain"]
            reconstructed += stems[name] * gain
        residual_rms = float(np.sqrt(np.mean((mix - reconstructed) ** 2)) + 1e-12)
        residual_db = round(20.0 * np.log10(residual_rms), 2)

        # 2. Voiceover ducking attenuation benchmark
        narr_path = os.path.join(tmp, "narr.wav")
        t_narr = np.arange(sr * 20) / sr
        narr = np.zeros_like(t_narr, dtype=np.float32)
        narr[int(4 * sr):int(10 * sr)] = (0.3 * np.sin(2 * np.pi * 200 * t_narr[int(4 * sr):int(10 * sr)])).astype(np.float32)
        sf.write(narr_path, narr, sr)

        out_duck = os.path.join(tmp, "duck")
        manifest_duck, _ = generate(
            {"prompt": "ambient tech pulse", "duration_s": 20, "seed": 3, "narration_url": narr_path, "ducking": {"depth_db": 12.0}},
            out_duck,
        )
        normal_mix, _ = sf.read(os.path.join(out_duck, "mix.wav"), dtype="float32")
        ducked_mix, _ = sf.read(os.path.join(out_duck, "mix_ducked.wav"), dtype="float32")

        speech_slice = slice(int(5 * sr), int(9 * sr))
        rms_norm = float(np.sqrt(np.mean(normal_mix[speech_slice] ** 2)) + 1e-12)
        rms_duck = float(np.sqrt(np.mean(ducked_mix[speech_slice] ** 2)) + 1e-12)
        measured_duck_db = round(20.0 * np.log10(rms_duck / rms_norm), 2)

        # 3. Single-stem regeneration invariance benchmark
        out_regen = os.path.join(tmp, "regen")
        req_regen = {**req_std, "variants": {"drums": 1}}
        _, stems_regen = generate(req_regen, out_regen, only_stems=["drums"], prior_stems=stems)
        unchanged_stems = [
            name for name in STEMS if name != "drums" and np.array_equal(stems[name], stems_regen[name])
        ]
        drums_changed = not np.array_equal(stems["drums"], stems_regen["drums"])

        # 4. Error handling verification
        caught_codes = []
        for bad_req in [
            {"prompt": "test", "duration_s": 2},
            {"prompt": "test", "duration_s": 10, "narration_url": "http://127.0.0.1:9/missing.wav"},
        ]:
            try:
                generate(bad_req, os.path.join(tmp, "err"))
            except EngineError as exc:
                caught_codes.append(exc.code)

        return {
            "engine_version": manifest["engine"]["version"],
            "generation_30s_runtime_s": gen_time_s,
            "realtime_factor": round(30.0 / max(gen_time_s, 1e-6), 1),
            "length_error_ms": length_error_ms,
            "sum_of_stems_residual_db": residual_db,
            "integrated_lufs": round(lufs(mix, sr), 2),
            "true_peak_dbtp": round(true_peak_db(mix, sr), 2),
            "ducking_target_db": -12.0,
            "ducking_measured_under_speech_db": measured_duck_db,
            "ducking_segments_detected": len(manifest_duck["ducking"]["speech_segments_s"]),
            "single_stem_regen_isolated": drums_changed and len(unchanged_stems) == 3,
            "unchanged_stems_on_regen": unchanged_stems,
            "verified_error_codes": caught_codes,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect quality and performance metrics.")
    parser.add_argument("--out", default="metrics_report.json", help="Output JSON path")
    args = parser.parse_args()

    report = measure_all()
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()