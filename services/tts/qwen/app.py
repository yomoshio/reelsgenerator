"""HTTP wrapper around Qwen3-TTS with the same API as the VoxCPM2 service, so the worker
cannot tell them apart.

Voices are the same reference clips in /voices: `narrator.wav` with its transcript in
`narrator.txt`. The Base model clones the clip, and takes its pace and its manner from
it: a clip told with feeling gives a narrator who tells. The clip itself comes from the
VoiceDesign model, through design_voice.py.
"""

import gc
import io
import os
import threading
from pathlib import Path
from typing import Any

import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from qwen_tts import Qwen3TTSModel

MODEL_ID = os.environ.get("QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
LANGUAGE = os.environ.get("QWEN_TTS_LANGUAGE", "Russian")
VOICES = Path(os.environ.get("VOICES_DIR", "/voices"))

app = FastAPI(title="tts")
_lock = threading.Lock()
_model: Qwen3TTSModel | None = None
_prompts: dict[tuple[str, float], Any] = {}


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    voice: str = "narrator"
    # VoxCPM's knobs; this model has none, so they are taken and ignored.
    cfg: float = 2.0
    steps: int = 10


def _loaded() -> Qwen3TTSModel:
    global _model  # noqa: PLW0603 - one model per process, loaded on first request
    if _model is None:
        _model = Qwen3TTSModel.from_pretrained(MODEL_ID, device_map="cuda:0", dtype=torch.bfloat16)
    return _model


def _clone_prompt(model: Qwen3TTSModel, voice: str) -> Any:
    """The voice's clone prompt, made once per reference clip and kept while it is unchanged."""
    reference = VOICES / f"{voice}.wav"
    transcript = VOICES / f"{voice}.txt"
    if not reference.exists() or not transcript.exists():
        raise HTTPException(404, f"no reference clip with a transcript for voice {voice!r}")
    key = (voice, reference.stat().st_mtime)
    if key not in _prompts:
        _prompts[key] = model.create_voice_clone_prompt(
            ref_audio=str(reference),
            ref_text=transcript.read_text(encoding="utf-8").strip(),
            x_vector_only_mode=False,
        )
    return _prompts[key]


@app.post("/speak")
def speak(req: SpeakRequest) -> Response:
    with _lock:
        model = _loaded()
        wavs, rate = model.generate_voice_clone(
            text=req.text, language=LANGUAGE, voice_clone_prompt=_clone_prompt(model, req.voice)
        )
    buffer = io.BytesIO()
    sf.write(buffer, wavs[0], rate, format="WAV", subtype="PCM_16")
    return Response(buffer.getvalue(), media_type="audio/wav")


@app.post("/unload", status_code=204)
def unload() -> None:
    global _model  # noqa: PLW0603
    with _lock:
        _model = None
        _prompts.clear()
        gc.collect()
        torch.cuda.empty_cache()


@app.get("/health")
def health() -> dict[str, bool]:
    return {"loaded": _model is not None}
