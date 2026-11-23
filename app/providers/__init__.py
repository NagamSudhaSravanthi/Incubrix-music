"""Provider registry + timeout + fallback."""
import concurrent.futures
import json
import os

from ..config import get_settings
from ..engine.errors import EngineError
from .flaky import FlakyProvider
from .mock import MockProvider
from .procedural import ProceduralProvider

REGISTRY = {"procedural": ProceduralProvider, "mock": MockProvider, "flaky": FlakyProvider}
FALLBACK_CODES = {"PROVIDER_ERROR", "PROVIDER_TIMEOUT"}


def get_provider(name):
    if name not in REGISTRY:
        raise EngineError("UNKNOWN_PROVIDER", f"Unknown provider '{name}'. Available: {sorted(REGISTRY)}", http_status=500)
    return REGISTRY[name]()


def _run(provider, req, outdir, progress, timeout_s):
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(provider.generate, req, outdir, progress)
    try:
        return fut.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        raise EngineError("PROVIDER_TIMEOUT", f"Provider '{provider.name}' did not finish within {timeout_s:.0f}s.",
                          retryable=True, details={"provider": provider.name}, http_status=504)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def run_with_fallback(req, outdir, progress):
    """Returns (manifest, directory_with_the_files). Each attempt gets its own folder so a hung provider cannot corrupt the next one."""
    s = get_settings()
    names = [s.provider] + ([s.fallback_provider] if s.fallback_provider and s.fallback_provider != s.provider else [])
    for i, name in enumerate(names):
        attempt_dir = os.path.join(outdir, f"attempt{i}")
        os.makedirs(attempt_dir, exist_ok=True)
        try:
            manifest = _run(get_provider(name), req, attempt_dir, progress, s.job_timeout_s)
        except EngineError as e:
            if e.code in FALLBACK_CODES and i + 1 < len(names):
                progress(20)
                failed = (name, e.code)
                continue
            raise
        if i > 0:
            manifest["warnings"].append({"code": "PROVIDER_FALLBACK_USED",
                                         "message": f"Provider '{failed[0]}' failed ({failed[1]}); the result was produced by fallback provider '{name}'."})
            with open(os.path.join(attempt_dir, "music_manifest.json"), "w") as f:
                json.dump(manifest, f, indent=2)
        return manifest, attempt_dir
