import type { Project, Scene } from "./types";

export type SourceLine = { speaker: string; text: string };

export const CUE = /^[A-Z][A-Z .'\-]{0,38}(?:\s*\([^)]*\))?$/;
export const SLUG = /^\s*(?:(?:\d+[.)]?\s+)?(?:INT\.?\/EXT\.?|EXT\.?\/INT\.?|I\/E\.?|INT\.?|EXT\.?)(?=[\s.])|scene\s+\d+\b)/i;

/** The same rule the server uses to number source dialogue lines, so "source line 3" means the same thing on both sides. */
export function parseSourceDialogue(text: string): SourceLine[] {
  const lines = text.split("\n");
  const out: SourceLine[] = [];
  let prevSpeaker = "";
  let prevEnd = -1;
  for (let i = 0; i < lines.length; ) {
    const ln = lines[i].trim();
    if (ln && CUE.test(ln) && !SLUG.test(ln) && i + 1 < lines.length && lines[i + 1].trim()) {
      const block: string[] = [];
      let j = i + 1;
      while (j < lines.length && lines[j].trim()) block.push(lines[j++].trim());
      const speaker = ln.replace(/\s*\([^)]*\)$/, "");
      const key = speaker.toLowerCase();
      const contd = /\(\s*CONT[\u2019']D\s*\)/i.test(ln);
      const nothingBetween = prevEnd >= 0 && lines.slice(prevEnd, i).every((x) => !x.trim());
      // same rule as the server: a (CONT'D) that exists only because of a page break continues the previous speech
      if (contd && key === prevSpeaker && nothingBetween && out.length) out[out.length - 1].text += " " + block.join(" ");
      else out.push({ speaker, text: block.join(" ") });
      prevSpeaker = key;
      prevEnd = j;
      i = j;
    } else i++;
  }
  return out;
}

export function describeEvents(p: Project, scene: Scene): string[] {
  const name = (id: string) => p.characters.find((c) => c.id === id)?.name ?? id;
  const prop = (id: string) => p.props.find((x) => x.id === id)?.name ?? id;
  return scene.state_changes.map((e) => {
    const item = e.kind.startsWith("prop") ? prop(e.item) : e.item;
    return `${e.kind.replaceAll("_", " ")}: ${name(e.character_id)}${item ? `, ${item}` : ""}${e.to_character_id ? ` to ${name(e.to_character_id)}` : ""}`;
  });
}
