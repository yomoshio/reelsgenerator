import zipfile
from pathlib import Path

import pytest

from reelsmith.books import passages, read_book

FB2 = """<?xml version="1.0" encoding="windows-1251"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info><book-title>Лапа</book-title></title-info></description>
<body><title><p>Часть первая</p></title>
<section><p>Ночь, <emphasis>ливень</emphasis>.</p><p>Стук в дверь.</p></section></body>
<body name="notes"><section><p>Примечание переводчика</p></section></body>
</FictionBook>"""

CONTAINER = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>"""

OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
<manifest><item id="two" href="two.xhtml"/><item id="one" href="one.xhtml"/></manifest>
<spine><itemref idref="one"/><itemref idref="two"/></spine></package>"""


def test_passages_keep_paragraphs_whole_and_cut_long_ones_between_sentences() -> None:
    long = "Длинное предложение номер раз. " * 10
    text = f"Первый абзац.\n\nВторой абзац.\n\n{long}"

    found = passages(text, size=80)

    assert found[0] == "Первый абзац.\n\nВторой абзац."
    assert all(len(p) <= 80 for p in found)
    assert " ".join(" ".join(found).split()) == " ".join(text.split())
    assert passages("абвгдежзийклмноп", size=10) == ["абвгдежзий", "клмноп"]


def test_books_are_read_from_plain_text_fiction_book_and_epub(tmp_path: Path) -> None:
    old = tmp_path / "old.txt"
    old.write_bytes("Глава один.\n\nГлава два.".encode("cp1251"))
    fb2 = tmp_path / "paw.fb2"
    fb2.write_bytes(FB2.encode("cp1251"))
    epub = tmp_path / "paw.epub"
    with zipfile.ZipFile(epub, "w") as book:
        book.writestr("mimetype", "application/epub+zip")
        book.writestr("META-INF/container.xml", CONTAINER)
        book.writestr("OEBPS/content.opf", OPF)
        book.writestr(
            "OEBPS/one.xhtml", "<html><head><title>x</title></head><body><p>Раз.</p></body></html>"
        )
        book.writestr(
            "OEBPS/two.xhtml",
            "<html><body><script>skip()</script><p>Два,<br/>три.</p></body></html>",
        )

    assert read_book(old) == "Глава один.\n\nГлава два."
    assert read_book(fb2) == "Часть первая\n\nНочь, ливень.\n\nСтук в дверь."
    assert read_book(epub) == "Раз.\n\nДва,\n\nтри."
    with pytest.raises(ValueError, match="fb2"):
        read_book(tmp_path / "paw.pdf")
