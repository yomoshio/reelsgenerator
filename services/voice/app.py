"""The narrator's voice by Chatterbox Multilingual: a text read in the voice of a reference
clip, with more life in it than Qwen3-TTS gives. It answers /speak as the speech service
does, so the pipeline only needs its address; when each word is said stays with whisper
in the speech service.

Voices are the same clips in /voices: `narrator.wav`. No transcript is needed. How lively
the reading is comes from the environment: CHATTERBOX_EXAGGERATION (0.25 flat, 0.5 plain,
0.8 dramatic), CHATTERBOX_CFG (lower is slower and more deliberate) and
CHATTERBOX_TEMPERATURE.

Russian is read with its stresses marked. /stress marks a text with a plus before each
stressed vowel (RUAccent, on the processor); /speak reads such a text, and one without
marks is read as the model guesses."""

import gc
import io
import os
import re
import threading
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from ruaccent import RUAccent

VOICES = Path(os.environ.get("VOICES_DIR", "/voices"))
EXAGGERATION = float(os.environ.get("CHATTERBOX_EXAGGERATION", "0.55"))
CFG = float(os.environ.get("CHATTERBOX_CFG", "0.4"))
TEMPERATURE = float(os.environ.get("CHATTERBOX_TEMPERATURE", "0.75"))
LANGUAGES = {"uk": "ru", "be": "ru"}
# The model writes at most a thousand speech tokens, some forty seconds; a longer text is
# read a few sentences at a time and joined with the pause a narrator leaves between them.
MOST = 280
PAUSE = 0.18
ACCENTS = os.environ.get("RUACCENT_MODEL", "turbo3.1")
_PLUS = re.compile(r"\+([аеёиоуыэюя])", re.IGNORECASE)

app = FastAPI(title="voice")
_lock = threading.Lock()
_model: ChatterboxMultilingualTTS | None = None
_accents: RUAccent | None = None


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1600)
    voice: str = "narrator"
    language: str = "ru"


class StressRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    language: str = "ru"


def accented(text: str) -> str:
    """A plus before a vowel becomes the stress mark the model was taught, after it."""
    return _PLUS.sub("\\1\u0301", text).replace("+", "")


def _speaker() -> ChatterboxMultilingualTTS:
    global _model  # noqa: PLW0603 - one model per process, loaded on first request
    if _model is None:
        _model = ChatterboxMultilingualTTS.from_pretrained(device=torch.device("cuda"))
    return _model


def pieces(text: str, most: int = MOST) -> list[str]:
    """The text in runs of whole sentences, each no longer than `most` where it can be."""
    out: list[str] = []
    found = re.findall(r"[^.!?…]+[.!?…]+[»\")]*|[^.!?…]+$", text.strip())
    for sentence in (part.strip() for part in found if part.strip()):
        if out and len(out[-1]) + len(sentence) + 1 <= most:
            out[-1] += " " + sentence
        else:
            out.append(sentence)
    return out or [text.strip()]


@app.post("/stress")
def stress(req: StressRequest) -> dict[str, str]:
    global _accents  # noqa: PLW0603
    if req.language != "ru":
        return {"text": req.text}
    with _lock:
        if _accents is None:
            _accents = RUAccent()
            _accents.load(omograph_model_size=ACCENTS, use_dictionary=True)
        return {"text": _accents.process_all(req.text)}


@app.post("/speak")
def speak(req: SpeakRequest) -> Response:
    reference = VOICES / f"{req.voice}.wav"
    if not reference.exists():
        raise HTTPException(404, f"no reference clip for voice {req.voice!r}")
    language = LANGUAGES.get(req.language, req.language)
    with _lock:
        model = _speaker()
        if language not in model.get_supported_languages():
            raise HTTPException(400, f"Chatterbox does not speak {req.language!r}")
        takes = [
            model.generate(
                accented(piece), language_id=language, audio_prompt_path=str(reference),
                exaggeration=EXAGGERATION, cfg_weight=CFG, temperature=TEMPERATURE,
            ).squeeze(0).cpu().numpy()
            for piece in pieces(req.text)
        ]  # fmt: skip
        rate = model.sr
    gap = np.zeros(round(PAUSE * rate), dtype=np.float32)
    joined = np.concatenate([part for take in takes for part in (take, gap)][:-1])
    buffer = io.BytesIO()
    sf.write(buffer, joined, rate, format="WAV", subtype="PCM_16")
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
    return {"speaker": _model is not None}
