# KNOWN_LIMITATIONS

Written to be read before the evaluator finds these. Each says what is missing, why it matters, and what the fix would be.

## Where the system is less rigorous than it looks
| Gap | What actually happens | Fix I would build next |
|---|---|---|
| **Events are not grounded** | Extraction checks that every character and prop *name* appears in the scene text. The *events* (who hands what to whom, injuries, what a character learns) are taken from the model unverified, and the continuity checker, though deterministic, runs on them. A missed or invented event gives a missed or invented finding. | Require a verbatim quote per event and check it is in the scene text. |
| **Story coverage is self-reported** | The rewrite verifier checks every source dialogue line is adapted in order by the same speaker (real checks), but "every source event is shown" relies on the model listing event numbers per line. It does not check the line depicts the event. | A judge pass (NLI or a second model) per event, with the verdict shown to the reviewer. |
| **Citations are checked for existence, not relevance** | A decision citing a pack fact passes if the fact id exists. A wrong but real id is not caught. | Compare the decision text with the cited fact (embedding similarity or a judge) and flag weak matches. |
| **No knowledge-contradiction rule** | What each character knows is tracked scene by scene, but no rule fires when a character acts on something they cannot yet know. Injuries only produce an INFO note, never a block. | Add those rules; they are small once events are grounded. |
| **Visual consistency is not measured** | Consistency comes from conditioning every later image on the approved reference image. It held in the sample run *by eye*. The automatic image check only catches blank, corrupt or wrongly shaped images. | Face-embedding similarity against the reference, plus colour checks per costume, with a threshold that marks an image for redo. |

## Cultural accuracy
- **No native-speaker review.** The Majhi pack (45 facts, 17 flagged) was drafted with AI and cross-checked by a second model; that is not verification. Gurmukhi spelling and register need a native reader.
- **The cultural checks catch known errors, not new ones.** The identity-marker list (23 terms) and the avoid list (8 terms) were drafted from mistakes seen in real runs; they are pack data marked as unreviewed. A name kept from the source is caught only when it is very similar (Samir → Samar is caught; Mira → Meera is not).
- **Observed model errors** in real runs: source names barely changed; a shop and a lawyer given religious or caste surnames the source did not establish; English words spelled out in Gurmukhi; a Sanskritised register (ਪ੍ਰਵੇਸ਼) instead of rural speech. The checks above now flag these; a person still has to judge the result.
- **One culture pack.** Adding one is data-only and one project holds exactly one pack, so nothing can be shared between cultures, but no second pack has been run, so separation is shown by design, not by test.

## Images
- More than 4 characters in a scene: only 4 are passed as reference images; the rest are described in words.
- Text inside images (signs, labels) is not controlled and may be garbled script.
- On a rate-limited tier generation is serial: about 8-12 minutes for 12 images.

## Pipeline
- Evaluated on one 5-scene gold set (characters F1 0.83; dialogue counts and 3/3 continuity traps correct). Too small to claim general accuracy; not tried on long scripts.
- DOCX: paragraph text only (tables and text boxes are skipped). Scanned PDFs need OCR, which is not supported.
- Jobs are tracked in memory: a server restart forgets a running job (progress already saved to disk is kept, and a rerun resumes).
- The plan's cast call is one serial model call (~2 minutes) and is the main latency cost.

## Product
- Local, single-user tool: no login, no multi-user editing (the last save wins).
- Scene fields cannot be edited directly; characters, merges and plan entries can.
- Latency, token and cost figures are measured (see `ARCHITECTURE.md`) but not shown in the UI.
