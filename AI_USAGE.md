# AI_USAGE

A plain account of where AI is used in the product, where it was used to build it, what it got wrong, and what has and has not been checked by a person.

## 1. AI inside the product
| Step | Model | What it does | What limits it |
|---|---|---|---|
| Reading each scene; proposing which names are the same person | gpt-4.1-mini (Azure Foundry) | Turns a scene into structured records | Names must appear in the scene; code decides whether a merge is applied |
| Cultural plan; rewriting the screenplay | gpt-5 (Azure Foundry) | Proposes adaptation decisions with reasons; writes the Gurmukhi | The culture pack, checks in code, and a person's approval |
| Character, costume and scene images | gpt-image-2 (Azure Foundry) | Generates images, later ones built on the approved reference image | A fixed specification per image, and a person's review |

AI is **not** used for: the continuity checks, the approval gates, deciding which images are out of date, or the export. Those are plain code.

## 2. AI used to build the project
Nearly all of the code, tests and documents were written by **Claude Code** (Claude Sonnet 5.5 and Opus 5.5), working from my instructions in one long session.
What I decided: the assignment and the culture (Majhi Punjabi), that nothing culture-specific is hard-coded, that there is one model switch with no fallback, that a person approves before images are made, a light interface, trimming the interface to the required screens, and deploying the image model in Azure. I also asked for the slow run to be stopped and optimised, and for an approach like an AI engineer's (measure, test, enforce limits in code) and not just prompt calling.
I have not read every line of the generated code line by line; correctness rests on the tests and checks in section 4.

## 3. What the AI got wrong, and how it was noticed
| What went wrong | How it was noticed | What changed |
|---|---|---|
| Assumed a free Gemini key could make images | A test call returned quota 0 | Moved image generation to an Azure deployment |
| Reported that a background run had started, when it had failed to start | Checking the running processes | Re-launched and checked before reporting |
| The first cultural plan came back partly in Gurmukhi, with mixed scripts and descriptive "names" | Reading the output | Added checks for English-only fields, mixed scripts and name shape |
| The model invented record IDs, which blocked approval | A real run | Unknown IDs are now detached and flagged, not treated as fatal |
| PDF text reading dropped blank lines: a 6-line conversation read as 2 | The accuracy check on the sample PDF | Switched to a layout-preserving reader |
| A speaker cue ("DESAI") was not matched to its character | The accuracy check on the sample PDF | Improved the speaker matching |
| Image requests failed with "not found" on the Foundry project address | Probing the endpoints directly | Images are now sent to the resource address |
| A test failed about 1 run in 4 (it set concurrency before building its test data) | Noticed in a full test run, then repeated 30 times | Fixed the test |
| The plan kept most source names, and gave a shop and a lawyer religious or caste surnames the story never mentions | Reviewing the output, when Claude was asked to critique its own work (see section 4) | Added code checks for unchanged names and religion or caste words, using lists in the culture pack |
| The rewrite wrote English words in Gurmukhi letters (Friday, buyer, ledger) | The same review | Added a list of words to avoid; every line is checked |
| The costume folder held 1 image for 7 costumes (first looks reuse the character image) | The same review | The export now lists every costume and says which image shows it |

## 4. How the AI's output was checked
- **Automated tests:** 365 tests using a fake model and a fake image model, so they need no keys.
- **An accuracy check on a hand-labelled screenplay:** scores scene, character, prop, dialogue and continuity results. **Limits:** the sample screenplay and its answer key were also written with AI help, it is a single 5-scene script, and characters scored 83%.
- **Checks inside the pipeline:** names must appear in the text, no dialogue line may be lost, output must be in the right script, and continuity is calculated by code.
- **Screenshots of most pages** in the recorded demo, checked by eye. The buttons and forms in live mode have not been click-tested in a browser.
- **A self-review:** I gave Claude a prompt asking it to attack the work as a hostile reviewer. It found real gaps (listed in `KNOWN_LIMITATIONS.md`), but it is the same AI reviewing its own work, not an independent review.
- **The culture pack:** its facts were drafted with AI and cross-checked by a second model, which is not proof.

## 5. What no person has verified
- **No native speaker has reviewed** the culture facts or the Gurmukhi. 17 of the 45 facts are marked unverified, and spelling and word-choice mistakes are likely.
- **Face and clothing consistency in the images** was judged by eye. No automatic measure exists.
- **The current sample output** was produced with approvals set by a script, not by a person reviewing each decision. It will be replaced by a run that I review and approve myself.
- **Model answers differ between runs.** The same screenplay can produce different names and wording, so the sample is one example, not a fixed result.
