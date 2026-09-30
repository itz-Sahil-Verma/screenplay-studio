"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api } from "./api";

/** The project, re-fetched every 2s while a background job is running, so progress appears without a refresh. */
export function useProject(id: string) {
  return useQuery({
    queryKey: ["project", id],
    queryFn: () => api.project(id),
    refetchInterval: (q) => (q.state.data?.job?.state === "running" ? 2000 : false),
  });
}

export function useProjects() {
  return useQuery({ queryKey: ["projects"], queryFn: api.projects, refetchInterval: 5000 });
}

export function usePacks() {
  return useQuery({ queryKey: ["packs"], queryFn: api.packs });
}

export function errorMessage(e: unknown): string {
  return e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong";
}

/**
 * Runs a change against the API, shows the outcome as a toast, then refreshes the project.
 * `act` returns a promise of the API result; `ok` turns it into a success message (or null for none).
 */
export function useAct(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ run }: { run: () => Promise<unknown>; ok?: (r: unknown) => string | null }) => run(),
    onSuccess: (result, vars) => {
      const msg = vars.ok ? vars.ok(result) : null;
      if (msg) toast.success(msg);
      qc.invalidateQueries({ queryKey: ["project", id] });
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["blockers", id] });
      qc.invalidateQueries({ queryKey: ["export-status", id] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
}
