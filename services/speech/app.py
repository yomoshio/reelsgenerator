"""The speech service: Qwen3-TTS reads a text in the narrator's voice, and faster-whisper
says when each word of a reading is heard. Both on one GPU, both loaded on first use and
dropped together by /unload.

Voices are reference clips in /voices: `narrator.wav` with its transcript `narrator.txt`.
The Base model clones the clip and takes its pace and manner from it; the clip itself comes
from the VoiceDesign model, through design_voice.py."""

import gc
import io
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from faster_whisper import WhisperModel
from pydantic import BaseModel, Field
from qwen_tts import Qwen3TTSModel

TTS_MODEL = os.environ.get("QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3")
WHISPER_COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8_float16")  # about half of float16
LANGUAGES = {"ru": "Russian", "en": "English", "uk": "Russian", "be": "Russian"}
VOICES = Path(os.environ.get("VOICES_DIR", "/voices"))

app = FastAPI(title="speech")
_lock = threading.Lock()
_tts: Qwen3TTSModel | None = None
_whisper: WhisperModel | None = None
_prompts: dict[tuple[str, float], Any] = {}


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    voice: str = "narrator"
    language: str = "ru"


def _speaker() -> Qwen3TTSModel:
    global _tts  # noqa: PLW0603 - one model per process, loaded on first request
    if _tts is None:
        _tts = Qwen3TTSModel.from_pretrained(TTS_MODEL, device_map="cuda:0", dtype=torch.bfloat16)
    return _tts


def _listener() -> WhisperModel:
    global _whisper  # noqa: PLW0603
    if _whisper is None:
        _whisper = WhisperModel(WHISPER_MODEL, device="cuda", compute_type=WHISPER_COMPUTE)
    return _whisper


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
        model = _speaker()
        wavs, rate = model.generate_voice_clone(
            text=req.text,
            language=LANGUAGES.get(req.language, "Russian"),
            voice_clone_prompt=_clone_prompt(model, req.voice),
        )
    buffer = io.BytesIO()
    sf.write(buffer, wavs[0], rate, format="WAV", subtype="PCM_16")
    return Response(buffer.getvalue(), media_type="audio/wav")


@app.post("/words")
def words(
    audio: UploadFile = File(...),  # noqa: B008 - FastAPI's way to take a file
    language: str = Form("ru"),
    hint: str = Form(""),
) -> list[dict[str, float | str]]:
    """Every word heard in the audio with when it starts and ends, in seconds. `hint` is the
    text that was read, which steers the spelling toward it."""
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        tmp.write(audio.file.read())
        tmp.flush()
        with _lock:
            segments, _ = _listener().transcribe(
                tmp.name, language=language, word_timestamps=True, initial_prompt=hint or None,
                vad_filter=False, beam_size=5,
            )  # fmt: skip
            found = [
                {"text": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)}
                for s in segments
                for w in s.words or []
            ]
    return found


@app.post("/unload", status_code=204)
def unload() -> None:
    global _tts, _whisper  # noqa: PLW0603
    with _lock:
        _tts, _whisper = None, None
        _prompts.clear()
        gc.collect()
        torch.cuda.empty_cache()


@app.get("/health")
def health() -> dict[str, bool]:
    return {"speaker": _tts is not None, "listener": _whisper is not None}
