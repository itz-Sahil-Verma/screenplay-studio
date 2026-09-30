# KNOWN_LIMITATIONS

What is not done or not verified yet, in plain words: what is missing, why it matters, and what we would build next.

## What the system checks, and what it only appears to check
The pipeline follows one rule: the AI proposes, plain code checks, a person approves. Most of it is genuinely checked in code
(gates, continuity rules, script purity, no lost dialogue). Five places are weaker than they look, and we would rather say so here.

**1. The AI's account of "what happened" is not checked against the script.**
- *Example:* the script says Meera hands the key to Ravi. The AI reads the scene and records that event. The continuity checker then follows the key from scene to scene.
- *The gap:* we check that the characters and props the AI names really appear in the scene, but not that the events it records really happen. If the AI misses the handover, or invents one, the continuity report is wrong, even though the checker itself is exact.
- *Next step:* make the AI quote the line of the script for each event, and check the quote is really there.

**2. "The rewrite kept the whole story" is partly the AI's own word.**
- *What is checked:* every original line of dialogue must appear in the rewrite, in the same order, from the same speaker. This is enforced in code.
- *The gap:* for story events (for example "Ravi takes the key"), the AI tells us which line shows it, and we accept that. We do not check the line really shows it.
- *Next step:* a second AI pass that reads each event and the line and answers yes or no, shown to the reviewer.

**3. A cultural decision can cite a fact that does not support it.**
- *Example:* a decision about greetings cites a pack fact about clothing. The fact exists, so the check passes.
- *The gap:* we confirm the cited fact is in the culture pack, not that it is relevant.
- *Next step:* compare the decision with the fact it cites and flag weak matches for the reviewer.

**4. Some continuity mistakes have no rule yet.**
- *Example:* a character reacts to news they could not yet know. Knowledge is tracked scene by scene, but nothing raises a warning. An injury produces a note, not a blocking error.
- *Next step:* add these rules. They are small once point 1 is solved.

**5. Do the same faces and clothes really match across images? Not measured.**
- *How consistency is achieved:* every later image is generated from the approved reference image of that character, so the same person and clothes carry over.
- *The gap:* in our sample run they looked consistent to the human eye. The automatic check only catches an image that is blank, corrupt or the wrong shape. It does not compare faces.
- *Next step:* compare each new image with the reference using face similarity and colour checks, and mark it for redo when it drifts.

## Cultural accuracy
- **No native speaker has reviewed the output.** The culture knowledge (45 facts, 17 of them marked unverified) was drafted with AI and checked by a second AI, which is not the same as a person who knows the culture. The Gurmukhi spelling and word choice need a native reader.
- **The cultural safety checks only catch mistakes we have already seen.** We keep two short lists: words that claim a religion or caste (23, such as a surname like "Singh"), and words that do not belong in rural Punjabi (8, such as English "Friday" written in Gurmukhi). They were written from errors seen in real runs, and they are not reviewed either. A name the AI left unchanged is caught only when it is very close to the original (Samir → Samar is caught; Mira → Meera is not).
- **Mistakes the AI made in real runs:** it kept most names from the source; it gave a shop and a lawyer religious or caste surnames that the story never mentioned; it wrote English words in Gurmukhi letters; and it used a formal, Hindi-like word where villagers would speak differently. The checks now flag these, but a person still has to judge the result.
- **Only one culture is included (Majhi Punjabi).** Adding another is meant to need only a new data file, and each project uses exactly one culture, so two cultures cannot mix. But we have not run a second culture, so this is true by design, not proven by a test.

## Images
- If a scene has more than four characters, only four get a reference image; the rest are described in words.
- Signs or lettering inside an image are not controlled and may show garbled script.
- On a rate-limited account, images are made one at a time: about 8 to 12 minutes for 12 images.

## Pipeline and testing
- Tested against one hand-labelled 5-scene screenplay: all scenes found, dialogue counts exact, all 3 planted continuity traps caught, and 83% accuracy on the character list. One script is too few to claim general accuracy, and nothing longer has been tried.
- Word documents: only the normal text is read (tables and text boxes are skipped). Scanned PDFs are not supported because there is no text recognition.
- If the server restarts while a job is running, the job is forgotten. Work already saved is kept, and running it again carries on from where it stopped.
- The slowest step is the cast plan: one AI call of about 2 minutes.

## Product
- A local, single-user tool: no login, and if two people edit at once the last save wins.
- Scene details cannot be edited directly; characters, merges and plan entries can.
- Speed, token and cost numbers were measured (see `ARCHITECTURE.md`) but are not shown in the app.
