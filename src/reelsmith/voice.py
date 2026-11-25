"""The voice step: every beat read in the style's voice, and when each written word is said.

A beat is read as one take. Whisper listens to it; a take where the narrator added words
the lines do not have, such as a stage direction read aloud, is read again, and the take
with the fewest additions is kept. Captions and cues use the words as written, numbers in
words and names spelled right; whisper only says when they are heard. A written word heard
differently, «двадцать» heard as «20», takes the time of what was heard in its place.

The reader is given the text with its stresses marked (`stress`); `spoken` in timing.json
is what it was given."""

import io
import json
import re
import wave
from collections.abc import Sequence
from difflib import SequenceMatcher
from pathlib import Path

import httpx

from reelsmith.captions import Word
from reelsmith.jobs import Context, Job
from reelsmith.story import Episode
from reelsmith.stress import fixes, kept, pinned
from reelsmith.text import bare, words

TAIL = 0.35  # the beat holds this long after its last word, room for the transition
_LATIN = re.compile(r"[a-z]", re.IGNORECASE)


class SpeechError(Exception):
    pass


class Speech:
    def __init__(
        self,
        url: str,
        *,
        reader: str = "",
        timeout: float = 600,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """`reader` is the address of the service that reads aloud, when it is not the one
        that listens: Chatterbox beside the speech service."""
        self._url = url.rstrip("/")
        self._reader = reader.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    async def speak(self, text: str, voice: str, language: str) -> bytes:
        response = await self._post(
            "/speak", at=self._reader, json={"text": text, "voice": voice, "language": language}
        )
        return response.content

    async def stress(self, text: str, language: str) -> str:
        """The text with a plus before each stressed vowel, from the reader that takes such
        marks; as written when the reader is the speech service, which does not."""
        if not self._reader:
            return text
        response = await self._post(
            "/stress", at=self._reader, json={"text": text, "language": language}
        )
        return str(response.json()["text"])

    async def words(self, audio: bytes, language: str, hint: str = "") -> list[Word]:
        response = await self._post(
            "/words",
            files={"audio": ("take.wav", audio, "audio/wav")},
            data={"language": language, "hint": hint},
        )
        return [Word(w["text"], float(w["start"]), float(w["end"])) for w in response.json()]

    async def unload(self) -> None:
        await self._post("/unload")
        if self._reader:
            await self._post("/unload", at=self._reader)

    async def _post(self, path: str, at: str = "", **kwargs: object) -> httpx.Response:
        url = at or self._url
        try:
            response = await self._client.post(url + path, **kwargs)  # type: ignore[arg-type]
        except httpx.HTTPError as exc:
            raise SpeechError(f"the speech service is unreachable at {url}: {exc}") from exc
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise SpeechError(
                f"speech {path} answered {response.status_code}: {response.text[:300]}"
            )
        return response


def seconds_of(audio: bytes) -> float:
    with wave.open(io.BytesIO(audio)) as w:
        return float(w.getnframes()) / float(w.getframerate())


def added(line: str, heard: Sequence[Word]) -> list[str]:
    """Words the narrator said that the line does not have. Only additions count: whisper
    writes numbers in digits and mishears a word now and then, neither is the narrator's
    fault. A single added word counts only when it is Latin in a line that has none."""
    wanted, said = words(line), [bare(w.text) for w in heard if bare(w.text)]
    extra: list[str] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=wanted, b=said, autojunk=False).get_opcodes():
        if tag == "insert":
            extra += said[j1:j2]
        elif tag == "replace" and j2 - j1 > i2 - i1:
            extra += said[j1 + i2 - i1 : j2]
    latin = not _LATIN.search(line) and any(_LATIN.search(w) for w in extra)
    return extra if len(extra) >= 2 or latin else []


def align(line: str, heard: Sequence[Word]) -> list[Word]:
    """The words of the line as written, each with the time it was heard. Runs of words
    heard differently share the time of what was heard in their place; words nobody heard
    take the gap between their neighbours."""
    written = line.split()
    if not written:
        return []
    if not heard:
        return _spread(written, 0.0, max(len(written) * 0.35, 0.5))
    keys = [bare(w) for w in written]
    matcher = SequenceMatcher(a=keys, b=[bare(w.text) for w in heard], autojunk=False)
    out: list[Word] = []
    for tag, w1, w2, h1, h2 in matcher.get_opcodes():
        if tag == "insert":
            continue
        if w2 - w1 == h2 - h1:
            pairs = zip(written[w1:w2], heard[h1:h2], strict=True)
            out += [Word(text, h.start, h.end) for text, h in pairs]
            continue
        start = heard[h1].start if h2 > h1 else (out[-1].end if out else heard[0].start)
        end = heard[h2 - 1].end if h2 > h1 else (heard[h1].start if h1 < len(heard) else start)
        out += _spread(written[w1:w2], start, max(end, start))
    return out


def _spread(texts: list[str], start: float, end: float) -> list[Word]:
    """Words laid one after another over a span, each as long as its letters."""
    sizes = [max(len(bare(t)), 1) for t in texts]
    step = (end - start) / sum(sizes) if end > start else 0.0
    out, t = [], start
    for text, size in zip(texts, sizes, strict=True):
        out.append(Word(text, t, t + size * step))
        t += size * step
    return out


async def voice(job: Job, folder: Path, ctx: Context) -> None:
    """The voice step: voice/beatNN.wav and voice/timing.json."""
    if ctx.speech is None:
        raise SpeechError("no speech service is set up")
    style = ctx.styles.get(job.style)
    ep = Episode.model_validate_json((folder / "episode.json").read_text(encoding="utf-8"))
    out = folder / "voice"
    out.mkdir(exist_ok=True)
    beats = []
    language = ctx.settings.language
    known = fixes(ctx.settings.stress)
    for n, beat in enumerate(ep.beats, 1):
        said = pinned(kept(beat.text, await ctx.speech.stress(beat.text, language)), known)
        best: tuple[bytes, list[Word], list[str]] | None = None
        for _ in range(ctx.settings.retakes + 1):
            take = await ctx.speech.speak(said, style.voice.name, language)
            heard = await ctx.speech.words(take, language, beat.text)
            extra = added(beat.text, heard)
            if best is None or len(extra) < len(best[2]):
                best = (take, heard, extra)
            if not extra:
                break
        assert best is not None
        take, heard, extra = best
        if extra:
            job.note("voice", note=f"beat {n} keeps added words: {' '.join(extra)}")
        (out / f"beat{n:02d}.wav").write_bytes(take)
        timed = align(beat.text, heard)
        beats.append(
            {
                "seconds": round(seconds_of(take) + TAIL, 3),
                "spoken": said,
                "words": [{"text": w.text, "start": w.start, "end": w.end} for w in timed],
            }
        )
    (out / "timing.json").write_text(
        json.dumps({"beats": beats}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    await ctx.speech.unload()
