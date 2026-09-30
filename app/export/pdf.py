"""PDF reports. fpdf2 + HarfBuzz shape Gurmukhi correctly (reportlab cannot). Fonts are bundled (SIL OFL)."""
from pathlib import Path

from fpdf import FPDF

from app.models import LineKind, Project

FONTS = Path(__file__).parent / "fonts"


def _pdf() -> FPDF:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.add_font("Latin", fname=str(FONTS / "NotoSans.ttf"))
    pdf.add_font("Gurmukhi", fname=str(FONTS / "NotoSansGurmukhi.ttf"))
    pdf.set_fallback_fonts(["Gurmukhi"])  # a Latin line that contains a Gurmukhi word still renders
    pdf.set_text_shaping(True)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()
    return pdf


def _write(pdf: FPDF, text: str, size: float = 11, font: str = "Latin", indent: float = 0, colour=(20, 20, 20), h: float = 6) -> None:
    pdf.set_font(font, size=size)
    pdf.set_text_color(*colour)
    pdf.set_x(pdf.l_margin + indent)
    pdf.multi_cell(0, h, text, new_x="LMARGIN", new_y="NEXT")


def adapted_screenplay_pdf(project: Project, gloss: bool = True) -> bytes:
    sel = project.selection
    names = {c.id: (c.adapted_name_native or c.adapted_name or c.name) for c in project.characters}
    pdf = _pdf()
    _write(pdf, "Adapted screenplay", 20, h=10)
    if sel:
        _write(pdf, f"{sel.pack_id.replace('_', ' ').title()} · {sel.region} · {getattr(sel.setting, 'value', sel.setting)}", 10, colour=(90, 90, 90))
    _write(pdf, "Machine-adapted draft. Lines marked (?) are uncertain and need a native reader. The grey line is an English gloss of the line above.",
           9, colour=(90, 90, 90))
    pdf.ln(4)
    for a in sorted(project.adapted_scenes, key=lambda a: a.source_scene_id):
        _write(pdf, a.heading, 13, "Gurmukhi", h=8)
        pdf.ln(1)
        for ln in a.lines:
            mark = " (?)" if ln.uncertain else ""
            if ln.kind == LineKind.DIALOGUE:
                _write(pdf, names.get(ln.character_id or "", ln.character_id or ""), 11, "Gurmukhi", indent=50)
                _write(pdf, ln.text + mark, 12, "Gurmukhi", indent=25, h=7)
            elif ln.kind == LineKind.SOUND:
                _write(pdf, f"({ln.text}){mark}", 11, "Gurmukhi", h=6.5)
            else:
                _write(pdf, ln.text + mark, 11, "Gurmukhi", h=6.5)
            if gloss and ln.gloss:
                _write(pdf, ln.gloss, 8.5, "Latin", indent=25 if ln.kind == LineKind.DIALOGUE else 0, colour=(120, 120, 120), h=4.5)
            pdf.ln(1.5)
        pdf.ln(4)
    return bytes(pdf.output())


def continuity_report_pdf(project: Project) -> bytes:
    pdf = _pdf()
    _write(pdf, "Continuity report", 20, h=10)
    n_err = sum(1 for w in project.warnings if w.severity.value == "error")
    _write(pdf, f"{len(project.scenes)} scenes · {len(project.characters)} characters · {len(project.props)} props · "
                f"{len(project.costumes)} costumes · {len(project.warnings)} findings ({n_err} errors)", 10, colour=(90, 90, 90))
    pdf.ln(3)
    _write(pdf, "Findings", 14, h=8)
    if not project.warnings:
        _write(pdf, "No continuity problems were found.", 11)
    for w in project.warnings:
        state = "accepted as intentional" if w.acknowledged else "open"
        _write(pdf, f"[{w.severity.value.upper()}] {w.code} · scenes {', '.join(w.affected_scene_ids) or '-'} · {state}", 10.5, h=6)
        _write(pdf, w.message, 10, indent=4, colour=(50, 50, 50), h=5)
        if w.ack_note:
            _write(pdf, f"Reviewer note: {w.ack_note}", 9.5, indent=4, colour=(90, 90, 90), h=5)
        pdf.ln(2)
    pdf.ln(3)
    _write(pdf, "Who wears what, scene by scene", 14, h=8)
    cn = {c.id: c.name for c in project.characters}
    for s in project.scenes:
        rows = "; ".join(f"{cn.get(c, c)}: {k}" for c, k in s.costumes.items()) or "-"
        _write(pdf, f"{s.scene_id} · {s.time or ''} {s.weather or ''}".strip(), 10.5, h=6)
        _write(pdf, rows, 9.5, indent=4, colour=(60, 60, 60), h=5)
    pdf.ln(3)
    _write(pdf, "Where each prop is, scene by scene", 14, h=8)
    pn = {p.id: p.name for p in project.props}
    for s in project.scenes:
        rows = "; ".join(f"{pn.get(p, p)} → {cn.get(h, h)}" for p, h in s.prop_holder_end.items()) or "-"
        _write(pdf, f"{s.scene_id} (end of scene)", 10.5, h=6)
        _write(pdf, rows, 9.5, indent=4, colour=(60, 60, 60), h=5)
    if project.user_edits:
        pdf.ln(3)
        _write(pdf, "Manual edits by the reviewer", 14, h=8)
        for e in project.user_edits:
            _write(pdf, "• " + e, 9.5, h=5)
    return bytes(pdf.output())
