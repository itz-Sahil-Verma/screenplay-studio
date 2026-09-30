"""Step 4: screenplay -> raw per-scene extraction.

One LLM call per scene (small outputs, and a failed scene can be retried alone).
Scene boundaries and numbering come from code (ingestion), never from the model.
The model's claims are then checked against the source text: a character that
does not appear in the scene text is rejected as invented.
"""
import logging
import re
import time

from app.ingestion import split_scenes
from app.config import settings
from app.llm import LLMError
from app.llm.base import LLMClient, try_parse
from app.models import Project, SceneExtraction, SourceScene, StateChangeKind
from app.pipeline.parallel import run_parallel
from app.storage import JsonCache, default_cache, make_key

log = logging.getLogger(__name__)

SYSTEM = """You are a script supervisor extracting structured data from ONE scene of a screenplay.

Rules:
- Use ONLY what the scene text states or clearly implies. Never invent characters, props or events.
- Write character names exactly as they appear in the text (e.g. "RAVI"). Put other ways this
  scene refers to the same person (e.g. "the elder son", "R. Kumar") in other_names.
- Costume: record what a character wears only if the text says so; otherwise leave it empty.
- Props: list objects that matter to the story. Say who holds each at the start and end of the scene.
  If a prop changes hands, is left behind, or is put away, say so in `note`.
- events: record state changes (prop gained/lost/transferred, injury gained/healed, new knowledge,
  costume change, relationship change). Use exactly these kinds: prop_gain, prop_loss,
  prop_transfer, injury_gain, injury_heal, knowledge_gain, costume_change, relationship_change.
  EVERY event must fill `item` with WHAT changed: the prop, the injury (e.g. "cut on left palm"),
  what the character learned (e.g. "Ravi has a job offer in the city"), the new costume, or the
  new relationship. An event with an empty `item` is invalid. prop_transfer also needs to_character.
- Leave any unknown field as an empty string or empty list. Do not guess.
- Output valid JSON for the given schema and nothing else."""


def build_prompt(scene: SourceScene, total: int) -> str:
    return (
        f"This is scene {scene.number} of {total}. Heading: {scene.heading or '(none)'}\n"
        f"Set scene_number to {scene.number}.\n\n"
        f"--- SCENE TEXT ---\n{scene.text}\n--- END ---"
    )


VALID_KINDS = {k.value for k in StateChangeKind}


def client_id(client: LLMClient) -> str:
    """Provider + model/deployment, so the cache never mixes results across models."""
    return f"{client.name}:{getattr(client, 'deployment', None) or getattr(client, 'model', '')}"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def _phrase_in(text: str, phrase: str, plural: bool = False) -> bool:
    """Whole-word match on normalized text ('ann' must not match inside 'channel')."""
    phrase = _norm(phrase)
    if not phrase:
        return False
    if plural:  # match singular/plural in either direction: "letters" ~ "letter", "cup" ~ "cups"
        base = re.sub(r"(?:es|s)$", "", phrase) if len(phrase) > 3 else phrase
        return re.search(rf"(?<!\w){re.escape(base)}(?:s|es)?(?!\w)", text) is not None
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def verify_extraction(scene: SourceScene, ex: SceneExtraction) -> list[str]:
    """Deterministic checks of the model's claims against the source text."""
    problems = []
    text = _norm(scene.text)
    if not ex.characters:
        problems.append("no characters extracted")
    for c in ex.characters:
        if not _phrase_in(text, c.name):
            problems.append(f"character {c.name!r} does not appear in the scene text")
    for p in ex.props:
        words = [w for w in _norm(p.name).split() if len(w) > 2]
        if words and not any(_phrase_in(text, w, plural=True) for w in words):
            problems.append(f"prop {p.name!r} does not appear in the scene text")
    for ev in ex.events:
        if ev.kind not in VALID_KINDS:
            problems.append(f"event kind {ev.kind!r} is not one of {sorted(VALID_KINDS)}")
        if not ev.item.strip():
            problems.append(f"{ev.kind} event for {ev.character!r} has an empty item (say WHAT changed)")
        if ev.kind == StateChangeKind.PROP_TRANSFER.value and not ev.to_character.strip():
            problems.append(f"prop_transfer of {ev.item!r} has no to_character")
    return problems


def prepare_source(project: Project, text: str) -> list[str]:
    """Split the source into scenes (code, deterministic). Returns problems found."""
    scenes, problems = split_scenes(text)
    project.source_text = text
    project.source_scenes = [SourceScene(number=s.number, heading=s.heading, text=s.text) for s in scenes]
    project.extraction_problems = list(problems)  # replace, never accumulate across calls
    return problems


def extract_scene(
    project: Project,
    number: int,
    client: LLMClient,
    max_calls: int | None = None,
    cache: JsonCache | None = None,
) -> SourceScene:
    """Extract (or re-extract) a single scene. Safe to call again after a failure.

    `max_calls` is ONE budget of model calls for this scene (default LLM_MAX_RETRIES). It is
    spent on whatever goes wrong first: invalid JSON or failed verification. So a scene costs
    at most max_calls model calls (each with a bounded transient retry inside the client).
    """
    max_calls = max_calls or settings.llm_max_retries
    scene = next(s for s in project.source_scenes if s.number == number)
    scene.problems = []  # state is rebuilt on every attempt, never carried over
    total = len(project.source_scenes)
    prompt = build_prompt(scene, total)
    cache = cache or default_cache("extract")
    key = make_key(SYSTEM, prompt, client_id(client))
    hit = cache.get(key)
    if hit is not None:
        scene.extraction = SceneExtraction.model_validate(hit)
        scene.error = ""
        log.info("scene %s: cache hit (no LLM call)", number)
        return scene

    started = time.perf_counter()
    feedback: list[str] = []
    best: SceneExtraction | None = None  # latest parseable answer
    best_problems: list[str] = []
    calls = 0
    try:
        while calls < max_calls:
            calls += 1
            p = prompt
            if feedback:
                p += "\n\nYour previous answer had these problems, fix them:\n- " + "\n- ".join(feedback)
            ex, err = try_parse(client.complete_json(SYSTEM, p, SceneExtraction), SceneExtraction)
            if ex is None:
                feedback = [f"the JSON did not match the schema: {err}"]
                continue
            ex.scene_number = number  # code owns numbering
            best, best_problems = ex, verify_extraction(scene, ex)
            if not best_problems:
                break
            feedback = best_problems
        if best is None:
            raise LLMError(f"no valid output after {calls} model calls: {feedback[0]}")
    except Exception as e:  # noqa: BLE001: record the failure on the scene, don't abort the project
        scene.extraction = None
        scene.error = f"{type(e).__name__}: {str(e)[:300]}"
        log.error("scene %s extraction failed after %d call(s): %s", number, calls, scene.error)
        return scene

    scene.extraction = best
    scene.error = ""
    scene.problems = best_problems  # unresolved: kept, but visible for review
    if not best_problems:  # only verified results are cached
        cache.set(key, best.model_dump(mode="json"))
    log.info("scene %s extracted in %.1fs, %d call(s), via %s", number, time.perf_counter() - started, calls, client_id(client))
    return scene


def run_extraction(project: Project, client: LLMClient, on_progress=None) -> Project:
    """Extract every scene that has no result yet. Re-running only redoes failed scenes.

    Scenes are independent, so they run concurrently (LLM_CONCURRENCY). extract_scene() changes only its own
    scene, so the workers cannot collide; progress is reported from this thread as each scene finishes."""
    if not project.source_scenes:
        raise LLMError("no source scenes: call prepare_source() first")
    pending = [s.number for s in project.source_scenes if s.extraction is None]
    done = 0

    def apply(number, _result, error):
        nonlocal done
        if error is not None:  # extract_scene records model failures itself; this catches anything unexpected
            scene = next(s for s in project.source_scenes if s.number == number)
            scene.extraction, scene.error = None, f"{type(error).__name__}: {str(error)[:300]}"
        done += 1
        if on_progress:
            on_progress("Reading scenes", done, len(pending))

    run_parallel(pending, lambda n: extract_scene(project, n, client), apply, settings.llm_concurrency)
    failed = [s.number for s in project.source_scenes if s.extraction is None]
    if not failed and project.status.value == "created":
        from app.models import ProjectStatus

        project.transition(ProjectStatus.EXTRACTED)
    return project
