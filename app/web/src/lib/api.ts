import type { ApprovalKey, ApprovalResult, Pack, Project, ProjectSummary, Stage } from "./types";

/** The demo project is a recorded real run, served as a static file. It is read-only. */
export const DEMO_ID = "demo";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, "Cannot reach the API. Start it with: uvicorn app.main:app --port 8010");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep the status text */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

/** Every change goes through here, so the demo can never be modified. */
function guard(id: string) {
  if (id === DEMO_ID) throw new ApiError(403, "This is a read-only demo of a recorded run. Create a new adaptation to make changes.");
}

export const api = {
  packs: () => call<Pack[]>("/packs"),
  projects: () => call<ProjectSummary[]>("/projects"),
  project: async (id: string): Promise<Project> => {
    if (id === DEMO_ID) return (await fetch("/demo/project.json")).json();
    return call<Project>(`/projects/${id}`);
  },
  create: (form: FormData) => call<{ id: string; scenes: number; problems: string[] }>("/projects", { method: "POST", body: form }),

  run: (id: string, stage: Stage, force = false) => (guard(id), call(`/projects/${id}/run/${stage}${force ? "?force=true" : ""}`, json("POST"))),
  replanScene: (id: string, scene: string) => (guard(id), call(`/projects/${id}/replan/scene/${scene}`, json("POST"))),
  replanEntities: (id: string) => (guard(id), call(`/projects/${id}/replan/entities`, json("POST"))),
  rewriteScene: (id: string, scene: string) => (guard(id), call(`/projects/${id}/rewrite/scene/${scene}`, json("POST"))),
  recheck: (id: string) => (guard(id), call<Project>(`/projects/${id}/recheck`, json("POST"))),

  editCharacter: (id: string, cid: string, fields: Record<string, unknown>) =>
    (guard(id), call<{ affected_scenes: string[] }>(`/projects/${id}/characters/${cid}`, json("PATCH", fields))),
  merge: (id: string, kind: string, keep_id: string, drop_id: string) =>
    (guard(id), call<{ affected_scenes: string[] }>(`/projects/${id}/merge`, json("POST", { kind, keep_id, drop_id }))),
  editPlan: (id: string, kind: string, eid: string, fields: Record<string, unknown>) =>
    (guard(id), call<{ affected_scenes: string[] }>(`/projects/${id}/plan/${kind}/${eid}`, json("PATCH", fields))),
  keepScene: (id: string, scene: string) => (guard(id), call(`/projects/${id}/plan/scenes/${scene}/keep`, json("POST"))),
  reviewDecision: (id: string, did: string, status: string, adapted?: string, note = "") =>
    (guard(id), call(`/projects/${id}/decisions/${did}/review`, json("POST", { status, adapted: adapted ?? null, note }))),
  acknowledge: (id: string, warning_id: string, note: string, acknowledged = true) =>
    (guard(id), call<ApprovalResult>(`/projects/${id}/warnings/acknowledge`, json("POST", { warning_id, acknowledged, note }))),

  blockers: async (id: string, what: ApprovalKey) => (id === DEMO_ID ? { what, blockers: [] as string[] } : call<{ what: string; blockers: string[] }>(`/projects/${id}/blockers/${what}`)),
  approve: (id: string, what: ApprovalKey) => (guard(id), call<ApprovalResult>(`/projects/${id}/approve/${what}`, json("POST"))),
  unapprove: (id: string, what?: ApprovalKey) => (guard(id), call(`/projects/${id}/unapprove`, json("POST", { what: what ?? null }))),

  regenerateAsset: (id: string, aid: string) => (guard(id), call(`/projects/${id}/assets/${aid}/regenerate`, json("POST"))),
  assetUrl: (id: string, aid: string, v?: string) => (id === DEMO_ID ? `/demo/images/${aid}.jpg` : `/api/projects/${id}/assets/${aid}/file${v ? `?v=${v}` : ""}`),
  exportStatus: (id: string) => call<{ missing: string[]; exported: boolean; zip_ready: boolean }>(`/projects/${id}/export/status`),
  buildExport: (id: string, allowPartial = false) => (guard(id), call<{ zip: string }>(`/projects/${id}/export${allowPartial ? "?allow_partial=true" : ""}`, json("POST"))),
  exportUrl: (id: string) => `/api/projects/${id}/export/download`,
  screenplayUrl: (id: string, gloss: boolean) => `/api/projects/${id}/screenplay?gloss=${gloss}`,
};
