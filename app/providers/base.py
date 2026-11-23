"""Every music source sits behind this small interface and is chosen by MUSIC_PROVIDER. Add a new one = one new class."""
from typing import Callable, Protocol


class MusicProvider(Protocol):
    name: str
    version: str

    def generate(self, req: dict, outdir: str, progress: Callable[[int], None]) -> dict:
        """Write mix.wav, stems/*.wav, music_manifest.json (and mix_ducked.wav) into outdir. Return the manifest."""
