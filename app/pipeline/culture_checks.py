"""Deterministic cultural checks. The lists they use come from the culture pack, never from code.

- identity markers: a word that asserts religion, caste or community is allowed only when the source establishes it,
  a decision about that entity is marked uncertain (so a person reviews it), or a person wrote it themselves.
- kept names: a character whose adapted name is (nearly) the source name was probably not adapted at all.
- avoid terms: words that do not belong in this culture's output (e.g. English spelled out in Gurmukhi).
"""
import re
import unicodedata
from difflib import SequenceMatcher

from app.models import CulturePack, Project

_EDITED = re.compile(r"^edited plan \w+ (\S+?):")


def tokens(text: str) -> list[str]:
    """Words, lower-cased, without punctuation. Written by hand because regex word boundaries break inside
    Indic words (vowel signs are combining marks, not word characters)."""
    out, word = [], []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat[0] in "LMN":  # letters, marks, numbers
            word.append(ch)
        elif word:
            out.append("".join(word).lower())
            word = []
    if word:
        out.append("".join(word).lower())
    return out


def has_term(text: str, term: str) -> bool:
    """True if the (possibly multi-word) term occurs as whole words in text."""
    t, words = tokens(term), tokens(text)
    return bool(t) and any(words[i:i + len(t)] == t for i in range(len(words) - len(t) + 1))


def markers_in(text: str, pack: CulturePack, source: str) -> list[str]:
    """Identity markers in text that the source does not itself use."""
    return [m.term for m in pack.identity_markers if has_term(text, m.term) and not has_term(source, m.term)]


def name_kept(source: str, adapted: str) -> bool:
    a, b = " ".join(tokens(source)), " ".join(tokens(adapted))
    return bool(a and b) and SequenceMatcher(None, a, b).ratio() >= 0.8


def human_edited(project: Project) -> set[str]:
    """Entity ids a person has edited in the plan. Their choice stands: these checks do not second-guess it."""
    return {m.group(1) for e in project.user_edits if (m := _EDITED.match(e))}


def avoid_problems(text: str, pack: CulturePack, where: str) -> list[str]:
    out = []
    for t in pack.avoid_terms:
        if has_term(text, t.term):
            fix = f"; write {t.prefer!r} instead" if t.prefer else ""
            out.append(f"{where} uses {t.term!r}{f' ({t.note})' if t.note else ''}{fix}")
    return out
