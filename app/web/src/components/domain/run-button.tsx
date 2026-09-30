"use client";

import type { ComponentProps } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAct } from "@/lib/hooks";
import type { Stage } from "@/lib/types";
import { Spinner } from "./bits";
import { useWorkspace } from "./workspace";

const DONE: Record<Stage, string> = {
  analyse: "Analysis started",
  extract: "Extraction started",
  normalize: "Normalization started",
  plan: "Planning started",
  rewrite: "Rewrite started",
  visuals: "Image generation started",
};

/** Starts a background stage. Disabled while any job is running on this project. */
export function RunButton({ stage, children, force, ...props }: { stage: Stage; force?: boolean } & Omit<ComponentProps<typeof Button>, "onClick">) {
  const { id, project } = useWorkspace();
  const act = useAct(id);
  const busy = project.job?.state === "running" || act.isPending;
  return (
    <Button {...props} disabled={busy || props.disabled} onClick={() => act.mutate({ run: () => api.run(id, stage, force), ok: () => DONE[stage] })}>
      {busy ? <Spinner /> : null}
      {children}
    </Button>
  );
}
