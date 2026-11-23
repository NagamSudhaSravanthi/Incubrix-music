"""Mock provider for tests: same files and manifest, but cheap sine stems. Needs no keys and finishes instantly."""
import numpy as np

from ..engine.pipeline import generate
from ..engine.render import STEMS

FREQ = {"drums": 60.0, "bass": 110.0, "pads": 220.0, "melody": 440.0}


def _render_mock(plan, only=None):
    t = np.arange(plan.N) / plan.sr
    out = {}
    for n in (only or STEMS):
        x = (0.1 * np.sin(2 * np.pi * FREQ[n] * t)).astype(np.float32)
        fade = int(0.5 * plan.sr)
        x[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        x[-1] = 0.0
        out[n] = x
    return out


class MockProvider:
    name, version = "mock", "1.0"

    def generate(self, req, outdir, progress):
        info = {"name": "mock", "version": "1.0", "kind": "test double", "licence": "n/a (tests only)"}
        manifest, _ = generate(req, outdir, progress=progress, renderer=_render_mock, provider_info=info)
        return manifest
