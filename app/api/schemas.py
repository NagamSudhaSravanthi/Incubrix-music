from typing import Literal

from pydantic import BaseModel, Field


class Section(BaseModel):
    start_s: float = Field(description="Section start in seconds. Snapped to the nearest bar line.")
    mood: str = Field(default="", max_length=200)


class OutputOptions(BaseModel):
    sample_rate: Literal[44100, 48000] = 48000
    target_lufs: float = Field(default=-16.0, ge=-30, le=-8)
    formats: list[Literal["wav", "mp3"]] = ["wav", "mp3"]


class Ducking(BaseModel):
    depth_db: float = Field(default=12.0, description="How far the music drops under speech (clamped to 8-15 dB).")


class MusicJobRequest(BaseModel):
    prompt: str = Field(max_length=1000, description="Mood / style description (any language).")
    duration_s: float = Field(description="Track length in seconds, 5 to 300.")
    sections: list[Section] | None = None
    tempo_bpm: float | None = None
    key: str | None = Field(default=None, description='e.g. "C", "A minor", "F# major"')
    loopable: bool = False
    narration_url: str | None = Field(default=None, description="http(s) URL, or an upload:// reference from POST /api/v1/uploads")
    seed: int | None = None
    output: OutputOptions | None = None
    ducking: Ducking | None = None
    variants: dict[Literal["drums", "bass", "pads", "melody"], int] | None = Field(
        default=None, description="Per-stem variant number. Changing one regenerates only that stem.")
    callback_url: str | None = Field(default=None, description="Optional. Receives a POST signed with HMAC-SHA256 in X-IncuBrix-Signature.")


class RegenerateRequest(BaseModel):
    stem: Literal["drums", "bass", "pads", "melody"]
    variant: int | None = Field(default=None, description="Variant number; default = previous + 1")


class JobAccepted(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    status_url: str


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool
    details: dict = {}


class ErrorResponse(BaseModel):
    error: ErrorBody


class JobResult(BaseModel):
    files: dict[str, str] = Field(description="Relative file name -> download link (mix.wav, stems/drums.wav, music_manifest.json ...)")
    warnings: list[dict] = []
    summary: dict = {}


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress: int = Field(ge=0, le=100)
    created_at: str
    finished_at: str | None = None
    source_job_id: str | None = None
    result: JobResult | None = None
    error: ErrorBody | None = None


class UploadResult(BaseModel):
    url: str = Field(description="Use as narration_url")
    filename: str
    bytes: int


class Health(BaseModel):
    status: str
