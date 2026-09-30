import io
from pathlib import Path

import pytest

from app.ingestion import read_document, read_pasted, split_scenes

FIXTURE = Path(__file__).parent / "fixtures" / "sample_screenplay.txt"


def sample_text() -> str:
    return read_document(FIXTURE.read_bytes(), "sample_screenplay.txt").text


def test_sample_splits_into_four_scenes_in_order():
    scenes, problems = split_scenes(sample_text())
    assert len(problems) == 1 and "preamble" in problems[0]  # the title line only
    assert [s.number for s in scenes] == [1, 2, 3, 4]
    assert scenes[0].heading == "INT. FAMILY HOME - KITCHEN - EARLY MORNING"
    assert scenes[1].heading.startswith("EXT.")
    assert scenes[3].heading.startswith("INT/EXT.")


def test_no_source_text_is_lost():
    text = sample_text()
    scenes, _ = split_scenes(text)
    # every word, in order, from the first to the last: nothing dropped, nothing reordered
    assert " ".join(s.text for s in scenes).split() == text.split()


def test_no_source_text_is_lost_with_preamble_and_odd_spacing():
    text = "MY TITLE\nby someone\n\nINT. A - DAY\n" + "one two three four five six " * 3 + "\n\n\nEXT. B - NIGHT\n" + "seven eight nine ten eleven twelve " * 3
    scenes, _ = split_scenes(text)
    assert " ".join(s.text for s in scenes).split() == text.split()


def test_dialogue_is_not_mistaken_for_a_heading():
    text = "INT. ROOM - DAY\n\nA man.\n\nINTERNAL AFFAIRS\nHe says things " + "word " * 30
    scenes, _ = split_scenes(text)
    assert len(scenes) == 1


def test_preamble_is_kept_and_reported():
    scenes, problems = split_scenes(sample_text())
    assert scenes[0].text.startswith("THE LETTER")  # title kept on scene 1, never dropped
    assert any("preamble" in p for p in problems)


def test_no_headings_reports_and_keeps_text():
    scenes, problems = split_scenes("Just a paragraph of story with no scene headings at all.")
    assert len(scenes) == 1
    assert any("no scene headings" in p for p in problems)


def test_scene_count_outside_range_is_warned():
    text = "INT. A - DAY\n" + "word " * 20 + "\nINT. B - DAY\n" + "word " * 20
    _, problems = split_scenes(text)
    assert any("expects 3-5" in p for p in problems)


def test_unsupported_type_and_empty_file():
    assert "unsupported" in read_document(b"x", "a.rtf").problems[0]
    assert read_document(b"", "a.txt").problems == ["file is empty"]


def test_short_source_flagged():
    assert any("very short" in p for p in read_pasted("INT. A - DAY\nhi").problems)


def test_txt_encodings():
    text = "INT. घर - DAY\n" + "शब्द " * 60
    assert read_document(text.encode("utf-16"), "a.txt").text.startswith("INT. घर")
    assert read_document(text.encode("utf-8-sig"), "a.txt").text.startswith("INT. घर")


def test_docx_roundtrip():
    from docx import Document

    doc = Document()
    for line in sample_text().split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    res = read_document(buf.getvalue(), "s.docx")
    scenes, _ = split_scenes(res.text)
    assert len(scenes) == 4


def test_pdf_roundtrip_and_page_numbers_removed():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in sample_text().split("\n"):
        if y < 60:
            c.drawString(300, 30, "2")  # a page number
            c.showPage()
            y = 800
        c.drawString(40, y, line[:110])
        y -= 14
    c.save()
    res = read_document(buf.getvalue(), "s.pdf")
    scenes, _ = split_scenes(res.text)
    assert len(scenes) == 4
    assert "\n2\n" not in res.text


def test_scanned_pdf_is_reported():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.rect(50, 50, 100, 100)  # drawing only, no text: behaves like a scan
    c.save()
    res = read_document(buf.getvalue(), "scan.pdf")
    assert any("no extractable text" in p for p in res.problems)


def test_corrupt_pdf_does_not_crash():
    res = read_document(b"not a pdf", "bad.pdf")
    assert res.problems and res.text == ""


# ---- a real-format screenplay PDF (found by testing at the assignment's input size) ---------------------
FULL_PDF = Path(__file__).parent / "fixtures" / "sample_screenplay_full.pdf"
FULL_TXT = Path(__file__).parent / "fixtures" / "sample_screenplay_full.txt"


def test_a_real_screenplay_pdf_gives_the_same_scenes_as_its_plain_text():
    pdf = read_document(FULL_PDF.read_bytes(), "s.pdf")
    txt = read_document(FULL_TXT.read_bytes(), "s.txt")
    assert pdf.problems == []
    a, _ = split_scenes(pdf.text)
    b, _ = split_scenes(txt.text)
    assert [s.heading for s in a] == [s.heading for s in b] and len(a) == 5


def test_layout_lines_from_the_pdf_are_not_story_text():
    text = read_document(FULL_PDF.read_bytes(), "s.pdf").text
    import re
    stray = [ln for ln in text.split("\n") if re.fullmatch(r"\s*\d{1,3}\.\s*", ln) or "CUT TO" in ln or "(MORE)" in ln]
    assert stray == []


def test_a_speech_split_by_a_page_break_is_one_source_line_but_a_contd_after_action_is_not():
    from app.models import Character, Project, Scene
    from app.pipeline.rewrite import source_dialogue

    def lines(path, name):
        text = read_document(path.read_bytes(), name).text
        scenes, _ = split_scenes(text)
        p = Project()
        p.characters = [Character(id=f"CHAR_{n}", name=n.title()) for n in ("ARUN", "SAMIR", "MIRA", "LEELA", "PRIYA", "DESAI")]
        return [len(source_dialogue(p, Scene(scene_id=f"SC{s.number:02d}", number=s.number, source_text=s.text))) for s in scenes]

    from_pdf, from_txt = lines(FULL_PDF, "s.pdf"), lines(FULL_TXT, "s.txt")
    assert from_pdf == from_txt == [6, 6, 6, 7, 4]  # page breaks change nothing; scene 4's post-action (CONT'D) stays separate


@pytest.mark.parametrize("junk", ["(MORE)", "(CONTINUED)", "CONTINUED:", "12 CONTINUED:", "CUT TO:", "FADE IN:", "DISSOLVE TO:", "FADE OUT.", "7.", "Page 7", "- 7 -"])
def test_layout_markers_are_removed(junk):
    body = "INT. ROOM - DAY\n" + "word " * 60
    assert junk not in read_document(f"{body}\n{junk}\nmore words here".encode(), "a.txt").text.split("\n")


def test_real_story_lines_that_look_a_little_like_layout_are_kept():
    text = "INT. ROOM - DAY\n" + "word " * 60 + "\nHe says it is over.\nShe says: cut to the chase.\nThe fade in the paint is old.\n"
    out = read_document(text.encode(), "a.txt").text
    assert "cut to the chase" in out and "fade in the paint" in out
