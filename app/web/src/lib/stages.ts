import type { Project, Stage } from "./types";

export const STATUS_ORDER = ["created", "extracted", "normalized", "plan_ready", "approved", "rewritten", "generated", "exported"] as const;
export const rank = (p: Project) => STATUS_ORDER.indexOf(p.status as (typeof STATUS_ORDER)[number]);

export type StepKey = "extract" | "continuity" | "plan" | "approve" | "rewrite" | "visuals" | "export";
export type StepState = "done" | "current" | "todo" | "locked" | "running" | "failed";

export type Step = { key: StepKey; label: string; path: string; state: StepState; hint: string };

/** Which step a background job belongs to, so the stepper can show a spinner on it. */
function jobStep(name: string, r: number): StepKey | null {
  if (name.startsWith("analyse")) return r === 0 ? "extract" : r === 1 ? "continuity" : "plan"; // one job, several steps: follow the status
  if (name.startsWith("extract")) return "extract";
  if (name.startsWith("normalize")) return "continuity";
  if (name.startsWith("plan") || name.startsWith("replan")) return "plan";
  if (name.startsWith("rewrite")) return "rewrite";
  if (name.startsWith("visuals") || name.startsWith("regenerate")) return "visuals";
  return null;
}

export function buildSteps(p: Project): Step[] {
  const r = rank(p);
  const running = p.job?.state === "running" ? jobStep(p.job.name, r) : null;
  const failed = p.job?.state === "failed" ? jobStep(p.job.name, r) : null;
  const unreviewed = p.decisions.filter((d) => d.status === "proposed").length;
  const errors = p.warnings.filter((w) => w.severity === "error" && !w.acknowledged).length;
  const imgs = p.assets ?? [];
  const made = imgs.filter((a) => a.status === "generated").length;
  const approved = Object.values(p.approval).filter(Boolean).length;

  const step = (key: StepKey, label: string, path: string, doneAt: number, hint: string, lockedBelow = 0): Step => {
    let state: StepState = r >= doneAt ? "done" : r === doneAt - 1 ? "current" : r < lockedBelow ? "locked" : "todo";
    if (running === key) state = "running";
    else if (failed === key) state = "failed";
    else if (key === "continuity" && errors > 0 && state === "done") state = "failed"; // done, but something still blocks: never show a green tick
    return { key, label, path, state, hint };
  };

  return [
    step("extract", "Extract", "/extract", 1, r >= 1 ? `${p.scenes.length || p.source_scenes.length} scenes` : "Read the screenplay"),
    step("continuity", "Continuity", "/continuity", 2, errors ? `${errors} blocking: resolve` : p.continuity_checked ? `${p.warnings.length} findings` : "Check for contradictions"),
    step("plan", "Adapt", "/plan", 3, p.plan ? `${p.decisions.length} decisions · ${unreviewed ? `${unreviewed} to review` : "all reviewed"}` : "Plan the changes"),
    step("approve", "Approve", "/approve", 4, `${approved}/3 approved`),
    step("rewrite", "Rewrite", "/rewrite", 5, p.adapted_scenes.length ? `${p.adapted_scenes.length} scenes` : "Write it"),
    { ...step("visuals", "Visuals", "/visuals", 6, imgs.length ? `${made}/${imgs.length} images` : r >= 4 ? "Unlocked" : "Unlocks after approval", 4), state: running === "visuals" ? "running" : failed === "visuals" ? "failed" : r >= 6 ? "done" : r >= 4 ? "todo" : "locked" },
    { key: "export", label: "Export", path: "/export", state: r >= 7 ? "done" : r >= 5 ? "todo" : "locked", hint: "Get the pack" },
  ];
}

export type NextAction = { label: string; description: string; stage?: Stage; path?: string };

export function nextAction(p: Project): NextAction {
  const r = rank(p);
  const failedScenes = p.source_scenes.filter((s) => s.error).length;
  if (r === 0)
    return failedScenes
      ? { label: `Retry ${failedScenes} failed scene${failedScenes > 1 ? "s" : ""}`, description: "Only the scenes that failed are sent to the model again; everything already done is kept.", stage: "analyse" }
      : { label: "Analyse the screenplay", description: "Reads every scene, merges aliases, checks continuity and drafts the cultural plan in one go. Nothing is generated until you approve.", stage: "analyse" };
  if (r === 1) return { label: "Normalize and check continuity", description: "Merge aliases into one character, remove duplicates, and look for contradictions before anything is generated.", stage: "normalize" };
  if (r === 2) return { label: "Generate the adaptation plan", description: "GPT-5 proposes names, costumes, places, gestures and speech, and explains every choice.", stage: "plan" };
  if (r === 3) return { label: "Review the plan and approve", description: "Accept, edit or reject each decision, then approve characters, costumes and plan.", path: "/plan" };
  if (r === 4) return { label: "Rewrite the screenplay", description: "One scene at a time, in the chosen script, with every line traced to its source.", stage: "rewrite" };
  if (r === 5) return { label: "Generate the visual pack", description: "Character references first, then costume sheets, then one keyframe per scene, each built on the approved references.", stage: "visuals" };
  if (r === 6) return { label: "Export the pack", description: "The adapted screenplay, continuity report, scene breakdown and every image, packaged.", path: "/export" };
  return { label: "Compare source and adapted", description: "Read both versions side by side and trace any line back to its source.", path: "/rewrite" };
}

export function counts(p: Project) {
  return {
    scenes: p.scenes.length || p.source_scenes.length,
    characters: p.characters.length,
    errors: p.warnings.filter((w) => w.severity === "error").length,
    warnings: p.warnings.filter((w) => w.severity === "warning").length,
    infos: p.warnings.filter((w) => w.severity === "info").length,
    blocking: p.blocking_warning_ids.length,
    decisions: p.decisions.length,
    flagged: p.decisions.filter((d) => d.uncertain).length,
    unreviewed: p.decisions.filter((d) => d.status === "proposed").length,
    approvals: Object.values(p.approval).filter(Boolean).length,
    lines: p.adapted_scenes.reduce((n, a) => n + a.lines.length, 0),
  };
}

/** How far the project is through the pipeline, as a percentage. Derived from the real state, never invented:
 * each status reached is one of seven steps, and while images are being made the share finished counts too. */
export function progress(p: Project): number {
  const r = rank(p);
  const imgs = p.assets ?? [];
  const partial = r === 5 && imgs.length ? (imgs.filter((a) => a.status === "generated").length / imgs.length) * 0.95 : 0;
  return Math.round(((r + partial) / 7) * 100);
}

/** Decisions still waiting for a human: flagged ones first, since those cannot be bulk-accepted. */
export const pendingReviews = (p: Project) => p.decisions.filter((d) => d.status === "proposed").length;

/** W-01, W-02 ...: short, readable ids for findings (the stored id is a long content hash). */
export const warningNumber = (p: Project, id: string) => `W-${String(p.warnings.findIndex((w) => w.id === id) + 1).padStart(2, "0")}`;
