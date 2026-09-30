# Screenplay Studio: cultural screenplay and visual adaptation

Re-creates a short screenplay inside an **exact culture and dialect** (built and tested on *Majhi Punjabi, rural Amritsar, Gurmukhi*),
with every cultural decision explained, checked and approved by a person before anything is generated.

> **Status:** the full flow is built and tested end to end: extraction, continuity checking, the cultural plan, approval gates,
> the Gurmukhi rewrite, the visual pack (character bible, costume bible, scene keyframes) and export. Known gaps are in
> `KNOWN_LIMITATIONS.md`; how AI was used (and where it was wrong) is in `AI_USAGE.md`.

## How it works
`extract` → `normalize` → `continuity check` → `adaptation plan` → **human approval** → `rewrite` → `visuals` → `export`

The model **proposes**; plain code **verifies** (invented characters, lost dialogue lines, wrong scripts, continuity contradictions);
a person **approves**. Details in `ARCHITECTURE.md`.

## System requirements
- **OS:** macOS or Linux (developed on macOS); Windows works through WSL.
- **Python** 3.11+ (developed on 3.13) and **Node** 20+ (developed on Node 25). About 1 GB of RAM and 1 GB of disk (a finished pack is ~40 MB).
- **Network access and keys:** the pipeline calls a hosted model. One LLM provider: Azure OpenAI / Foundry (default), or Gemini, or Groq.
  Images need an image deployment on Azure Foundry (tested with `gpt-image-2`; FLUX.2 is also supported).
- **No keys? You can still run the tests** (365, fake models) **and browse the recorded demo** (`/projects/demo`).
- A sample environment file is `.env.example`: copy it to `.env` and fill it in (never commit `.env`).

## Setup
```bash
# 1. backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # then edit .env (see below)

# 2. frontend
cd app/web && npm install && cd ../..
```

### Choosing the model provider: one switch, no fallback
Set `LLM_PROVIDER` in `.env` to `azure`, `gemini` or `groq`; only that provider runs.
- **azure**: fill `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, and the deployment names `AZURE_DEPLOYMENT_EXTRACT` / `AZURE_DEPLOYMENT_ADAPT`.
- **gemini** (free key from Google AI Studio): `LLM_PROVIDER=gemini`, `GEMINI_API_KEY=...`.
- **groq**: `LLM_PROVIDER=groq`, `GROQ_API_KEY=...`.

### Choosing the image model: one switch, no fallback
- `IMAGE_PROVIDER=azure` (tested): `AZURE_DEPLOYMENT_IMAGE=<your gpt-image deployment name>`. Uses the same endpoint and key
  as the LLM. A Foundry *project* endpoint (`…/api/projects/<name>`) is fine: images are sent to the resource root automatically.
- `IMAGE_PROVIDER=azure_flux`: `AZURE_FLUX_MODEL=FLUX.2-pro` (or `FLUX.2-flex`).
- `IMAGE_CONCURRENCY=1` and `IMAGE_QUALITY=low` avoid rate-limit (429) errors on small tiers; use `medium` for the final pack.
- A full pack for 5 scenes / 6 characters is 12 images, about 8-12 minutes on a rate-limited tier.

## Run
```bash
# terminal 1: API   (port 8010; 8000 is often taken)
.venv/bin/uvicorn app.main:app --port 8010

# terminal 2: UI    (http://localhost:3000, proxies /api to the API)
cd app/web && npm run dev
```
If the API is on another address: `API_URL=http://host:port npm run dev`.

**No API key? Open `http://localhost:3000/projects/demo`**: a recorded real run you can browse read-only (the UI is the only thing you need running).

## Tests
```bash
.venv/bin/pytest -q            # 365 tests, no network, no API keys needed (fake LLM and fake image model)
cd app/web && npm run lint && npx tsc --noEmit
```
After changing an API response model: `scripts/gen_api_types.sh`.

## Where each deliverable is
| Required | Location |
|---|---|
| Working web application and source | `app/` (backend), `app/web/` (frontend) |
| README, setup, requirements, sample env | this file, `.env.example`, `requirements.txt` |
| Architecture, AI usage log, known limitations | `ARCHITECTURE.md`, `AI_USAGE.md`, `KNOWN_LIMITATIONS.md` |
| Automated tests | `tests/` (backend, 365 tests), `evals/` (gold-label scoring) |
| Sample adapted screenplay | `sample_output/adapted_screenplay.pdf` |
| Structured scene breakdown, continuity report | `sample_output/scene_breakdown.json`, `sample_output/continuity_report.pdf` |
| Character, costume and scene visual pack | `sample_output/character_bible/`, `costume_bible/`, `scene_keyframes/` (each image has a JSON with its model, prompt and spec) |
| Recorded demonstration | `demo_video.mp4` |

## Layout
```
app/           FastAPI backend: models, ingestion, llm, pipeline, culture_packs, storage, api, review
app/web/       Next.js + Tailwind + shadcn/ui frontend (light theme)
tests/         backend tests and fixtures (incl. the sample screenplay)
sample_output/ one full exported pack: adapted_screenplay.pdf, continuity_report.pdf, scene_breakdown.json,
               character_bible/, costume_bible/, scene_keyframes/ (every image with the JSON that reproduces it)
evals/         gold labels + scorer for extraction, continuity, plan and rewrite
workspace/     one folder per project (created at run time)
```

## Using it
1. **New adaptation**: paste or upload (TXT, DOCX, PDF; up to `MAX_UPLOAD_MB`, default 10), choose culture, region, setting, script.
2. **Analyse**: extraction, alias merging, continuity check and the cultural plan run as one job.
3. **Review**: fix or merge records (Extract), accept findings with a reason (Continuity), accept / edit / reject decisions (Adapt).
4. **Approve** characters, costumes and plan. Nothing is rewritten or generated before this.
5. **Rewrite**, then **Visuals** (references first, then costume sheets, then keyframes), then **Export** the ZIP.
Editing anything later closes the gate again; only the affected scenes and images are redone.
**Trace** (top right) follows one character or prop from the source text to its images.

## Culture packs
A culture is a JSON file in `app/culture_packs/packs/` (facts with sources, style rules, supported scripts). Adding a culture or a script
is a data change, not a code change. A pack also lists **identity markers** (words that assert religion, caste or community) and
**avoid terms** (e.g. English spelled out in Gurmukhi); code checks the plan and the rewrite against them. The Majhi pack's facts
and lists are AI-drafted and **not yet verified by a native speaker**; decisions that rely on unverified facts are flagged in the UI.
