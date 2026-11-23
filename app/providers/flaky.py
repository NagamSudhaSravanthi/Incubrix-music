"""Simulates an external music API that breaks mid-job. Used to demonstrate the 'provider fails or times out' hard case.
PROVIDER_FAIL_MODE=error -> raises PROVIDER_ERROR after 40% progress; =timeout -> hangs until the job timeout fires."""
import time

from ..config import get_settings
from ..engine.errors import EngineError


class FlakyProvider:
    name, version = "flaky", "demo"

    def generate(self, req, outdir, progress):
        s = get_settings()
        progress(40)
        if s.provider_fail_mode == "timeout":
            time.sleep(s.job_timeout_s + 5)
        raise EngineError("PROVIDER_ERROR", "The music provider returned an error in the middle of the job.", retryable=True,
                          details={"provider": "flaky"}, http_status=502)
