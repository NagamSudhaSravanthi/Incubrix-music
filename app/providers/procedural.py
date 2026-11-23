"""Default provider: original music synthesised by our own code. No keys, no cost, no third-party rights."""
from ..engine.pipeline import ENGINE_VERSION, generate


class ProceduralProvider:
    name, version = "procedural", ENGINE_VERSION

    def generate(self, req, outdir, progress):
        manifest, _ = generate(req, outdir, progress=progress)
        return manifest
