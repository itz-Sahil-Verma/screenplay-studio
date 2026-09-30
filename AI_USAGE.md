# AI_USAGE

## Where AI is used in the product
| Step | Model | Role | What limits it |
|---|---|---|---|
| Extraction, alias proposals | gpt-4.1-mini (Azure Foundry) | reads a scene into structured records | schema, grounding in source text, code applies merges |
| Adaptation plan, rewrite | gpt-5 | proposes cultural decisions with reasons; writes Gurmukhi | culture pack, verifiers, human approval |
| Images | gpt-image-2 (Azure Foundry) | character/costume/keyframe images conditioned on references | deterministic spec, human review |

Not used for: continuity checking, gates, staleness, export (all plain code).

## Where AI was used to build it
I built this with Claude Code (Claude) as a pair-programmer: scaffolding, models, pipeline, tests, UI, docs. I chose the
culture, the architecture rules (no hardcoded culture, single provider switch, approval gates, light theme), and the
priorities, and I reviewed and redirected the work.

## What the AI got wrong (and how it was caught)
- Assumed a free Gemini key could generate images. Measured: image quota was 0. Switched to an Azure deployment.
- Said a live run had started when it had failed to import. Caught by checking the process; relaunched.
- The first plan run returned Gurmukhi, mixed-script text and descriptive names → added English-only, mixed-script and name-shape checks.
- The model invented entity ids that blocked approval → unknown ids are now unlinked and flagged instead.
- PDF text extraction dropped blank lines, collapsing dialogue (2 lines instead of 6) → layout mode; found by the eval, not by eye.
- A cue ("DESAI") was unresolved → found by the eval; fixed in speaker lookup.
- The image endpoint returned 404 on a Foundry *project* URL (chat works there, images don't) → image client uses the resource root.
- A concurrency test was flaky (~1 in 4) because it raised concurrency before building a scripted fixture → fixed and run 30×.

- The first plan kept source names, and gave a shop and a lawyer religious / caste surnames the story never established → added
  pack-driven checks for kept names and identity markers (found by a red-team review of the output, not by a test).
- The rewrite spelled English words in Gurmukhi (ਫ੍ਰਾਇਡੇ for Friday) → an avoid list in the pack, checked on every line.
- The costume bible folder held one image for seven costumes, because first looks reuse the character reference → the export now
  writes every costume with its record and says which image shows it.

## How AI output was verified
Not by reading it and trusting it: by tests (365, run with a fake model), by a gold-label eval that scores extraction, continuity,
plan and rewrite, by deterministic checks inside the pipeline, by screenshots of every UI page, and by a separate red-team review
prompt aimed at finding where the system only looks rigorous (its findings are in `KNOWN_LIMITATIONS.md`).

## What was not human-verified (be honest)
- Culture pack facts were drafted with AI and cross-checked by a second model; **no native-speaker review has happened**. 17 facts are marked flagged/uncertain.
- The Gurmukhi rewrite has not been reviewed by a native reader; spelling errors are likely.
- The approvals in the sample project were set by a script to exercise the pipeline, **not** by a human reviewing each decision.
- Face/costume consistency in the sample images was judged by eye from contact sheets, not by an automated metric.
