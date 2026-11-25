from pathlib import Path

from reelsmith.stress import fixes, kept, pinned


def test_marks_are_kept_only_where_the_word_is_as_written() -> None:
    text = "Берег реки был пуст. Все уже ушли."
    marked = "Бер+ёг рек+и был п+уст. Вс+ё +уже ушл+и."
    assert kept(text, marked) == "Берег рек+и был пуст. Все +уже ушл+и."


def test_a_marking_that_lost_a_word_is_not_used() -> None:
    assert kept("Свет погас во всём доме.", "Св+ет пог+ас во д+оме.") == "Свет погас во всём доме."


def test_the_project_list_overrules_the_marker_and_keeps_the_capital(tmp_path: Path) -> None:
    listed = tmp_path / "stress.txt"
    listed.write_text("# заметка\nуж+е\nм+оррис\n\nбез пометки\n", encoding="utf-8")
    known = fixes(listed)
    assert known == {"уже": "уж+е", "моррис": "м+оррис"}
    assert pinned("+Уже ушл+и, сказ+ал Морр+ис.", known) == "Уж+е ушл+и, сказ+ал М+оррис."
    assert fixes(tmp_path / "none.txt") == {}
