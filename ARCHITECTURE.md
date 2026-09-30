# ARCHITECTURE

**Principle: the model proposes, code verifies, a human approves.** Every model output is a proposal that deterministic
code checks against the source text, the schema and the culture pack. Nothing reaches image generation until a person
approves characters, costumes and the plan.

## Pipeline

```
ingest → extract (LLM, per scene) → normalize (LLM proposes, code applies) → continuity check (code)
       → adaptation plan (LLM + culture pack) → 3 approval gates (human)
       → rewrite in target script (LLM, verified) → visual pack (image model) → export (code)
```

| Stage | Who decides | What checks it |
|---|---|---|
| Ingestion (TXT/DOCX/PDF, `app/ingestion`) | code | reports problems (scanned PDF, encrypted, too short); PDF layout mode keeps speaker gaps; page numbers, (MORE), CUT TO removed |
| Extraction (`app/pipeline/extract.py`) | LLM, one call per scene, run in parallel | schema validation, every record grounded in the scene text, retry only the failed scenes |
| Normalization (`normalize.py`) | LLM proposes alias merges; code applies | union-find; a merge the code cannot justify is rejected and logged; manual edits are never silently discarded |
| Continuity (`continuity.py`) | **code only** | state tracking of injuries, props (who holds what), costumes, time; warnings have stable ids so acknowledgements survive re-checks |
| Culture pack (`app/culture_packs/*.json`) | human-vetted data | every fact has sources, basis, confidence; an integrity validator; flagged facts are shown as uncertain |
| Plan (`plan.py`) | LLM (GPT-5): one cast call, then per-scene calls in parallel | size caps enforced in code, English-only / name-shape / mixed-script checks, every decision carries reason + basis + uncertainty |
| Approval (`review.py`, `Project` state machine) | **human** | blockers recomputed fresh; any later edit re-closes the gate |
| Rewrite (`rewrite.py`) | LLM per scene | source lines numbered; order and speaker checked; script purity by Unicode ranges; avoid terms from the pack |
| Images (`app/images`) | image model | see below |
| Export (`app/export`) | code | refuses an incomplete pack unless explicitly allowed |

## Cultural checks (`app/pipeline/culture_checks.py`)
Deterministic, with every word list in the pack:
- **Kept names**: an adapted name (nearly) equal to the source name must be changed or justified.
- **Identity markers**: a word asserting religion, caste or community (e.g. a surname, a place of worship) is allowed only if the
  source uses it, a decision about that entity is marked uncertain (so a person reviews it), or a person wrote it.
- **Avoid terms**: English spelled out in Gurmukhi, or another language's register, sends the scene back once with the preferred word.
Plan problems block approval until fixed or justified; a reviewer's own edit is never second-guessed.

## Nothing culture-specific is in code
A culture is a JSON pack (facts, style rules, cross-checks, allowed scripts); scripts are Unicode ranges in
`scripts.json`. Adding a culture or script is data-only. One project = one pack, so nothing leaks between cultures.

## One provider switch, no fallback
`LLM_PROVIDER` (azure | gemini | groq) and `IMAGE_PROVIDER` (azure | azure_flux) each select exactly one backend.
There is no fallback to another provider or model: a failure is recorded and retried on the same one. Models are chosen
per step (extraction: a small fast model; planning/rewrite: a reasoning model).

## Visual consistency (`app/images`)
- Specs are derived deterministically from approved records; the prompt is a pure function of the stored spec, so the
  spec reproduces the image.
- **One image per unique appearance**: a character's first costume *is* their reference; only later looks get a costume sheet.
- Phases: character references (text→image) → costume sheets → scene keyframes. Later phases use the *actual generated
  reference images* as inputs (image edit endpoint), so the same person/clothes carry over. This is conditioning on pixels, not on matching words.
- A spec hash includes the hashes of its reference assets: change a character and only their images (and scenes they are in) go stale.
- Per-asset failure isolation and retry; a failed reference fails only what depends on it.
- Deterministic checks (decodes, right shape, not blank). There is **no automated check that faces match**; that is a human review.

## Systems techniques
Parallel scene calls with single-thread state application (`run_parallel`); concurrency limit; per-call metrics
(latency, tokens); output budgets enforced by repair, not by hoping; prompt-hash cache; progressive per-scene saving so a
crash loses nothing and a re-run does only the missing work; explicit job status; project files replaced atomically.

## Measured
One 5-scene, 6-character PDF end to end: 294 s wall time, 17 model calls, 0 errors (plan 121 s, rewrite 166 s). Latency tracked
output length (~85 tokens/s), not reasoning, so the fixes were output caps enforced in code and parallel scene calls
(1.6x and 2.1x speed-up). Images: 12 in ~10 minutes at concurrency 1 (the tier rate-limits at 2).

## Evals and tests
`evals/` scores extraction, continuity, plan and rewrite against hand-made gold labels on a 5-scene PDF. `tests/`
(365) include barrier-based proofs that steps really run concurrently and gate tests proving images cannot be made before approval.

## Layout
`app/{ingestion,llm,pipeline,images,export,culture_packs,models,api,storage}`, `app/web` (Next.js), `evals/`, `tests/`,
`sample_output/`, `workspace/` (per-project runs, git-ignored).
