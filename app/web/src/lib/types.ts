import type { components } from "./api-types";

type S = components["schemas"];
/**
 * The API always sends every field (Pydantic defaults are serialised), so the "optional" markers OpenAPI adds
 * are safe to drop, at every depth. Real `null`s (e.g. `selection`, `age`) are kept.
 */
type R<T> = T extends null ? null : T extends (infer U)[] ? R<U>[] : T extends object ? { [K in keyof T]-?: R<Exclude<T[K], undefined>> } : T;

export type Project = R<S["ProjectView"]>;
export type ProjectSummary = S["ProjectSummary"];
export type JobInfo = S["JobInfo"];
export type Scene = R<S["Scene"]>;
export type SourceScene = R<S["SourceScene"]>;
export type Character = R<S["Character"]>;
export type Location = R<S["Location"]>;
export type Prop = R<S["Prop"]>;
export type Costume = R<S["Costume"]>;
export type Warning = R<S["ContinuityWarning"]>;
export type Decision = R<S["AdaptationDecision"]>;
export type AdaptedScene = R<S["AdaptedScene"]>;
export type AdaptedLine = R<S["AdaptedLine"]>;
export type AdaptationPlan = R<S["AdaptationPlan"]>;
export type EntityPlan = R<S["EntityPlan"]>;
export type ScenePlan = R<S["ScenePlan"]>;
export type CharacterPlan = R<S["CharacterPlan"]>;
export type CostumePlan = R<S["CostumePlan"]>;
export type LocationPlan = R<S["LocationPlan"]>;
export type PropPlan = R<S["PropPlan"]>;
export type StateChange = R<S["StateChange"]>;
export type ApprovalResult = S["ApprovalResult"];
export type ApprovalKey = "characters" | "costumes" | "plan";

/** /api/packs has no response model on the server, so this one is written by hand. */
export type Pack = {
  id: string;
  culture: string;
  regions: string[];
  settings: string[];
  scripts: { id: string; label: string }[];
  default_script: string;
  avoid_mixing_with: string[];
  facts: number;
  flagged_facts: number;
};

export type Stage = "extract" | "normalize" | "plan" | "rewrite" | "analyse" | "visuals";
export type Asset = R<S["Asset"]>;
