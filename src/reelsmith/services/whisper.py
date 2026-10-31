from __future__ import annotations

import asyncio
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from reelsmith.services.ffmpeg import Word

if TYPE_CHECKING:
    from faster_whisper import WhisperModel


class WhisperTranscriber:
    """Word timings for subtitles. Runs on CPU so it never competes for the GPU."""

    def __init__(self, model: str, language: str, threads: int = 8) -> None:
        self._model_name = model
        self._language = language
        self._threads = threads

    @cached_property
    def _model(self) -> WhisperModel:
        # Imported here: faster-whisper pulls in ctranslate2, which `add` and friends never need.
        from faster_whisper import WhisperModel  # noqa: PLC0415

        return WhisperModel(
            self._model_name, device="cpu", compute_type="int8", cpu_threads=self._threads
        )

    async def words(self, audio: Path) -> list[Word]:
        return await asyncio.to_thread(self._words, audio)

    def _words(self, audio: Path) -> list[Word]:
        segments, _ = self._model.transcribe(
            str(audio), language=self._language, word_timestamps=True, vad_filter=False
        )
        return [
            Word(w.word.strip(), w.start, w.end)
            for seg in segments
            for w in seg.words or ()
            if w.word.strip()
        ]
