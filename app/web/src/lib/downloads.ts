import type { Project } from "./types";

export function download(filename: string, content: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([content], { type: `${type};charset=utf-8` }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** scene_breakdown.json: the structured extraction, as required by the brief. */
export function sceneBreakdown(p: Project) {
  return {
    project: p.id,
    culture: p.selection,
    scenes: p.scenes.map((s) => ({ ...s, source_text: undefined })), // the full text is in project.json
    characters: p.characters,
    locations: p.locations,
    props: p.props,
    costumes: p.costumes,
  };
}

export function continuityReport(p: Project): string {
  const lines = [`# Continuity report`, ``, `Project ${p.id}. ${p.warnings.length} findings, ${p.blocking_warning_ids.length} blocking.`, ``];
  for (const sev of ["error", "warning", "info"] as const) {
    const ws = p.warnings.filter((w) => w.severity === sev);
    if (!ws.length) continue;
    lines.push(`## ${sev.toUpperCase()} (${ws.length})`, ``);
    for (const w of ws) {
      lines.push(`- **${w.code}** in ${w.affected_scene_ids.join(", ")}: ${w.message}`);
      if (w.acknowledged) lines.push(`  - Acknowledged: ${w.ack_note}`);
    }
    lines.push(``);
  }
  return lines.join("\n");
}

/** The adapted screenplay as readable text (same layout as the server's), built from the project so it works offline and in the demo. */
export function screenplayText(p: Project, gloss: boolean): string {
  const name = (id: string | null) => { const c = p.characters.find((x) => x.id === id); return c?.adapted_name_native || c?.name || ""; };
  const out: string[] = [];
  for (const a of [...p.adapted_scenes].sort((x, y) => x.source_scene_id.localeCompare(y.source_scene_id))) {
    out.push(a.heading, "");
    for (const l of a.lines) {
      const g = gloss && l.gloss ? `   [${l.gloss}]` : "";
      const mark = l.uncertain ? " (?)" : "";
      if (l.kind === "dialogue") out.push(`        ${name(l.character_id)}`, `    ${l.text}${mark}${g}`, "");
      else if (l.kind === "sound") out.push(`(${l.text})${mark}${g}`, "");
      else out.push(`${l.text}${mark}${g}`, "");
    }
  }
  return out.join("\n").trimEnd() + "\n";
}
