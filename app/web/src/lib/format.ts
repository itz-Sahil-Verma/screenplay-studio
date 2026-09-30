import type { Character, Project } from "./types";

export const STATUS_LABEL: Record<string, string> = {
  created: "Uploaded",
  extracted: "Extracted",
  normalized: "Normalized",
  plan_ready: "Plan ready",
  approved: "Approved",
  rewritten: "Rewritten",
  generated: "Images ready",
  exported: "Exported",
};

export const DIMENSION_LABEL: Record<string, string> = {
  verbal: "Speech",
  non_verbal: "Gesture",
  character: "Character",
  visual_world: "Look & world",
  story_world: "Story",
};

export const sceneNo = (id: string) => `Scene ${Number(id.replace(/\D/g, ""))}`;

/** The name people will see in the adapted story, falling back to the source name before approval. */
export const displayName = (c: Character | undefined, plan?: Project["plan"]) => {
  if (!c) return "";
  const planned = plan?.entities?.characters.find((x) => x.character_id === c.id);
  return c.adapted_name || planned?.name_roman || c.name;
};

export const nativeName = (c: Character | undefined, plan?: Project["plan"]) => {
  if (!c) return "";
  const planned = plan?.entities?.characters.find((x) => x.character_id === c.id);
  return c.adapted_name_native || planned?.name_native || "";
};

export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
