"""Split screenplay text into scenes by slugline, preserving order.

Rule-based on purpose: scene boundaries should be deterministic. The LLM (Step 4)
fills in the details of each scene, but it never decides where scenes start.
"""
import re
from dataclasses import dataclass

# "INT. KITCHEN - DAY", "EXT./INT. ROAD", "I/E CAR", optionally numbered ("3. INT. ...")
_SLUG = re.compile(
    r"^\s*(?:\d+[.)]?\s+)?(?:INT\.?/EXT\.?|EXT\.?/INT\.?|I/E\.?|INT\.?|EXT\.?)\s+\S.*$"
)
# "Scene 1 – Bus Station", "SCENE 2: Family House", "Scene 3. Hall" (any case): a plain-language heading with a number
_SCENE_WORD = re.compile(r"^\s*SCENE\s+\d+\b.*$", re.IGNORECASE)

EXPECTED_SCENES = (3, 5)  # from the brief; outside this we warn, we do not fail


@dataclass
class RawScene:
    number: int  # 1-based, in source order
    heading: str
    text: str  # full text including the heading line


def _is_heading(line: str) -> bool:
    return bool(_SLUG.match(line) or _SCENE_WORD.match(line))


def split_scenes(text: str) -> tuple[list[RawScene], list[str]]:
    """Returns (scenes, problems)."""
    problems: list[str] = []
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if _is_heading(ln)]

    if not starts:
        problems.append(
            "no scene headings found (expected lines like 'INT. KITCHEN - DAY'); "
            "treating the whole text as one scene"
        )
        return [RawScene(1, "", text.strip())], problems

    if starts[0] > 0 and "\n".join(lines[: starts[0]]).strip():
        problems.append(
            "text before the first scene heading was kept as a preamble on scene 1 "
            "(title page or notes?)"
        )
        starts[0] = 0  # never silently drop source text

    scenes = []
    for n, start in enumerate(starts, 1):
        end = starts[n] if n < len(starts) else len(lines)
        chunk = lines[start:end]
        heading = next((ln.strip() for ln in chunk if _is_heading(ln)), "")
        scenes.append(RawScene(n, heading, "\n".join(chunk).strip()))

    lo, hi = EXPECTED_SCENES
    if not lo <= len(scenes) <= hi:
        problems.append(f"found {len(scenes)} scenes; the brief expects {lo}-{hi}")
    tiny = [s.number for s in scenes if len(s.text.split()) < 15]
    if tiny:
        problems.append(f"scene(s) {tiny} have very little text; possible split error")
    return scenes, problems
