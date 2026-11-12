"""HTTP wrapper around VoxCPM2 so the worker can treat speech like any other service.

Voices are reference clips in /voices: `narrator.wav` with its transcript in
`narrator.txt`. Without a reference the model picks a voice from the text, which
changes between calls, so a channel should always ship one.
"""

import gc
import io
import os
import threading
from pathlib import Path

import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from voxcpm import VoxCPM

MODEL_ID = os.environ.get("VOXCPM_MODEL", "openbmb/VoxCPM2")
VOICES = Path(os.environ.get("VOICES_DIR", "/voices"))

app = FastAPI(title="tts")
_lock = threading.Lock()
_model: VoxCPM | None = None


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    voice: str = "narrator"
    cfg: float = 2.0
    steps: int = 10


def _loaded() -> VoxCPM:
    global _model  # noqa: PLW0603 - one model per process, loaded on first request
    if _model is None:
        # No torch.compile (the image has no C compiler) and no denoiser (it cleans other
        # people's recordings, and the reference clip here is made by the model itself).
        _model = VoxCPM.from_pretrained(MODEL_ID, optimize=False, load_denoiser=False)
    return _model


@app.post("/speak")
def speak(req: SpeakRequest) -> Response:
    reference = VOICES / f"{req.voice}.wav"
    transcript = VOICES / f"{req.voice}.txt"
    if not reference.exists():
        raise HTTPException(404, f"no reference clip for voice {req.voice!r}")

    words = transcript.read_text(encoding="utf-8").strip() if transcript.exists() else None

    with _lock:
        model = _loaded()
        # Only the line: with a reference clip VoxCPM2 continues the clip and reads a
        # direction in brackets aloud instead of following it.
        audio = model.generate(
            text=req.text,
            prompt_wav_path=str(reference),
            prompt_text=words,
            cfg_value=req.cfg,
            inference_timesteps=req.steps,
        )
        rate = model.tts_model.sample_rate

    buffer = io.BytesIO()
    sf.write(buffer, audio, rate, format="WAV", subtype="PCM_16")
    return Response(buffer.getvalue(), media_type="audio/wav")


@app.post("/unload", status_code=204)
def unload() -> None:
    global _model  # noqa: PLW0603
    with _lock:
        _model = None
        gc.collect()
        torch.cuda.empty_cache()


@app.get("/health")
def health() -> dict[str, bool]:
    return {"loaded": _model is not None}
