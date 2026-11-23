import json
from pathlib import Path

import httpx

from reelsmith.captions import Word
from reelsmith.jobs import Jobs, Source
from reelsmith.story import Episode
from reelsmith.voice import Speech, added, align, voice
from tests.fakes import DATA, FakeLlm, FakeSpeech, context


def _heard(*pairs: tuple[str, float]) -> list[Word]:
    return [Word(text, start, start + 0.3) for text, start in pairs]


def test_a_number_heard_in_digits_keeps_the_written_word_and_the_heard_time() -> None:
    heard = _heard(("Через", 0.1), ("20", 0.5), ("минут", 1.0), ("гаснет", 1.4))
    timed = align("Через двадцать минут гаснет", heard)
    assert [w.text for w in timed] == ["Через", "двадцать", "минут", "гаснет"]
    assert timed[1].start == 0.5
    assert timed[3].start == 1.4


def test_a_word_nobody_heard_takes_the_gap_between_its_neighbours() -> None:
    heard = _heard(("Он", 0.0), ("стучит", 1.0))
    timed = align("Он тихо стучит", heard)
    assert 0.3 <= timed[1].start < timed[2].start


def test_only_added_words_count_against_the_narrator() -> None:
    line = "Вода поднимается на этаж в час."
    assert added(line, _heard(*[(w, i) for i, w in enumerate(line.split())])) == []
    assert added(
        line, _heard(("Пауза", 0), ("тихо", 0.3), *[(w, 1 + i) for i, w in enumerate(line.split())])
    ) == ["пауза", "тихо"]
    assert (
        added(line, _heard(("Вода", 0), ("поднимается", 1), ("на", 2), ("1", 3), ("этаж", 4))) == []
    )


async def test_a_take_with_added_words_is_read_again(tmp_path: Path) -> None:
    ep = Episode.model_validate_json((DATA / "flood-01.json").read_text(encoding="utf-8"))
    ep = ep.model_copy(update={"beats": ep.beats[:2]})
    speech = FakeSpeech(extra=("читает", "медленно"))
    ctx = context(tmp_path, FakeLlm())
    ctx.speech = speech
    jobs = Jobs(ctx.settings.jobs)
    job = jobs.create(Source(kind="idea", text="x"), "blackout")
    folder = jobs.folder(job)
    (folder / "episode.json").write_text(ep.model_dump_json())
    await voice(job, folder, ctx)
    assert speech.spoken.count(ep.beats[0].text) == 2
    timing = json.loads((folder / "voice" / "timing.json").read_text())
    assert len(timing["beats"]) == 2
    assert timing["beats"][0]["words"][0]["text"] == ep.beats[0].text.split()[0]
    assert (folder / "voice" / "beat02.wav").is_file()
    assert speech.unloaded


async def test_chatterbox_reads_and_the_speech_service_listens() -> None:
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if request.url.path == "/words":
            return httpx.Response(200, json=[])
        return httpx.Response(200, content=b"RIFF")

    speech = Speech(
        "http://ears:8000", reader="http://mouth:8001", transport=httpx.MockTransport(answer)
    )
    await speech.speak("Свет гаснет.", "narrator", "ru")
    await speech.words(b"RIFF", "ru")
    await speech.unload()
    await speech.close()
    assert asked == [
        "http://mouth:8001/speak", "http://ears:8000/words",
        "http://ears:8000/unload", "http://mouth:8001/unload",
    ]  # fmt: skip


async def test_without_a_reader_the_speech_service_reads_too() -> None:
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=b"RIFF")

    speech = Speech("http://ears:8000", transport=httpx.MockTransport(answer))
    await speech.speak("Свет гаснет.", "narrator", "ru")
    await speech.unload()
    await speech.close()
    assert asked == ["http://ears:8000/speak", "http://ears:8000/unload"]
