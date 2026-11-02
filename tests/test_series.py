from pathlib import Path

from reelsmith.cli import ideas
from reelsmith.models import Character, EpisodeIdea, Season
from reelsmith.series import Serial, bible, episode_brief, ideas_file, make_serial, write_serial
from reelsmith.services.synthetic import SyntheticLlm
from tests.fakes import outline, style


def _season(episodes: int = 3) -> Season:
    return Season(
        title="Потоп",
        world="Ночью прорвало дамбу.",
        characters=[Character(name="Лена", look="10 лет, жёлтая куртка, красная рация")],
        episodes=[
            EpisodeIdea(title=f"Часть {n}", logline=f"цель {n}") for n in range(1, episodes + 1)
        ],
    )


def test_each_episode_brief_carries_the_world_the_looks_and_the_two_before() -> None:
    brief = episode_brief(_season(4), 3)

    assert brief.startswith("Series «Потоп», episode 4 of 4, «Часть 4».")
    assert "copy their looks exactly: Лена: 10 лет, жёлтая куртка, красная рация" in brief
    assert "Episode 2: цель 2 Episode 3: цель 3" in brief
    assert "Episode 1:" not in brief
    assert brief.endswith("This episode: цель 4")


def test_the_ideas_file_has_one_queueable_line_per_episode() -> None:
    serial = Serial(_season(3), [outline(f"Часть {n}") for n in range(1, 4)])

    lines = ideas_file(serial, "serial").splitlines()

    found = ideas(lines)
    assert [style for _, style, _ in found] == ["serial"] * 3
    assert found[1][2].startswith("«Потоп», episode 2 of 3, «Часть 2». Часть 2. Characters:")


def test_the_bible_lists_people_episodes_and_every_beat() -> None:
    text = bible(Serial(_season(2), [outline("Утро"), outline("Ключ")]))

    assert "| Лена | 10 лет, жёлтая куртка, красная рация |" in text
    assert "| 2 | Часть 2 | цель 2 |" in text
    assert "### 2. Ключ" in text
    assert "6. beat 5" in text


async def test_a_serial_is_planned_episode_by_episode_and_written_out(tmp_path: Path) -> None:
    made = await make_serial(SyntheticLlm(), "Ночью прорвало дамбу выше по реке", style(), 4)

    notes, queue = write_serial(made, "fake", tmp_path, "flood")

    assert len(made.outlines) == 4
    assert notes.read_text(encoding="utf-8").startswith("# Ночью прорвало дамбу")
    assert len(ideas(queue.read_text(encoding="utf-8").splitlines())) == 4
