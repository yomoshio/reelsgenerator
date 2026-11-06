from reelsmith.checks import present, problems, unsaid_plates
from reelsmith.models import Character, Overlay, Script, Shot
from tests.fakes import style


def flood(*shots: Shot) -> Script:
    return Script(
        title="Потоп",
        hook="water at the knees",
        hook_kind="threat",
        characters=[
            Character(name="Артём", look="man, 30, short dark hair, blue raincoat"),
            Character(name="Лена", look="girl, 10, yellow hooded jacket, red toy radio"),
        ],
        shots=list(shots),
        music="drone",
    )


def shot(line: str, *plates: Overlay, cast: tuple[str, ...] = ("Артём",), motion: str = "") -> Shot:
    return Shot(
        line=line,
        picture="p",
        motion=motion or "water ripples, slow push-in",
        cast=list(cast),
        stress=[line.split(maxsplit=1)[0]],
        overlays=list(plates),
    )


def plates(script: Script) -> list[tuple[int, str]]:
    return [(i, o.text) for i, o in unsaid_plates(script)]


def test_a_goal_plate_before_the_narrator_names_the_goal_is_early() -> None:
    goal = Overlay(kind="goal", text="ЦЕЛЬ: девятый этаж, мастерская")

    script = flood(
        shot("Артём просыпается: вода по колено.", goal),
        shot("Наверх, на девятый этаж, в мастерскую.", goal),
        shot("Лестница одна.", goal),
    )

    assert plates(script) == [(0, "ЦЕЛЬ: девятый этаж, мастерская")]


def test_a_number_on_a_plate_must_be_said_in_its_own_shot() -> None:
    script = flood(
        shot("Третий этаж из девяти.", Overlay(kind="count", text="ЭТАЖ 3 ИЗ 9")),
        shot("Шкаф перегородил лестницу.", Overlay(kind="count", text="ЭТАЖ 4 ИЗ 9")),
        shot("Пятый этаж.", Overlay(kind="count", text="ЭТАЖ 5 ИЗ 9")),
    )

    assert plates(script) == [(1, "ЭТАЖ 4 ИЗ 9")]


def test_a_plate_repeated_from_the_shot_before_carries_on() -> None:
    count = Overlay(kind="count", text="ЭТАЖ 32")

    script = flood(
        shot("Тридцать второй этаж.", count),
        shot("Свет гаснет.", count),
        shot("Тишина.", count),
    )

    assert plates(script) == []


def test_plates_match_words_in_any_case_form_and_skip_labels_and_numbering() -> None:
    script = flood(
        shot("Это Лена с красной рацией.", Overlay(kind="card", text="Лена | красная рация")),
        shot("Не открывай дверь.", Overlay(kind="rule", text="1. Не открывай дверь")),
        shot("Рация загорается сама.", Overlay(kind="alert", text="РАЦИЯ АКТИВНА")),
    )

    assert plates(script) == [(2, "РАЦИЯ АКТИВНА")]


def test_a_person_named_in_the_line_must_be_in_the_frame() -> None:
    script = flood(
        shot("Вода поднимается, Артём должен бежать наверх.", cast=()),
        shot("Фонарик Артёма гаснет.", cast=("Артём",)),
        shot("Лене страшно.", cast=("Артём",)),
    )

    assert [p for p in problems(script, style()) if "`cast`" in p] == [
        "Named in the line but missing from `cast`: shot 1 (Артём), shot 3 (Лена). "
        "Whoever the line names is in the picture and in `cast`."
    ]
    assert present(script.shots[2], script) == ["Артём", "Лена"]


def test_camera_moves_that_reveal_what_is_not_drawn_are_refused() -> None:
    script = flood(
        shot("Вода.", motion="Camera tilts up from the water to the dark upper floor."),
        shot("Шкаф.", motion="The wardrobe shifts slightly, slow push-in."),
        shot("Лестница.", motion="Camera pans slowly to the ceiling."),
    )

    assert [p for p in problems(script, style()) if "camera" in p.lower()] == [
        "Camera moves that make the video model invent what is outside the picture: "
        "shot 1 'tilts', shot 3 'pans'. The camera only holds or pushes in slowly."
    ]


def test_pictures_and_looks_written_in_russian_are_refused() -> None:
    script = flood(shot("Раз."), shot("Два."), shot("Три."))
    script.shots[1].picture = "Открытая дверь соседней квартиры."
    script.characters[0].look = "30 лет, короткие тёмные волосы, синий дождевик"

    assert problems(script, style()) == [
        "Write `picture` and `motion` in English: shots 2.",
        "Write the look of Артём in English; the image model reads English.",
    ]


def test_too_many_empty_shots_in_a_row_are_refused() -> None:
    script = flood(
        shot("Артём просыпается."),
        shot("Дверь.", cast=()),
        shot("Лифт.", cast=()),
        shot("Лестница.", cast=()),
        shot("Артём идёт."),
    )

    assert "Shots 2 to 4 show nobody" in " ".join(problems(script, style()))
    script.shots[2].cast = ["Артём"]
    assert "show nobody" not in " ".join(problems(script, style()))
