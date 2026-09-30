"use client";

import { TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import type { JobInfo } from "@/lib/types";
import { Spinner } from "./bits";

const MESSAGE: [string, string][] = [
  ["analyse", "Reading every scene, merging aliases, checking continuity and drafting the plan. Finished scenes are saved as they complete."],
  ["extract", "Reading each scene into structured records and checking every claim against the source text."],
  ["normalize", "Merging aliases into one character, removing duplicates and checking continuity."],
  ["replan", "Re-planning with the model. Unchanged scenes come back instantly from the cache."],
  ["plan", "GPT-5 is planning the adaptation: names, costumes, places, gestures and speech. This can take several minutes."],
  ["rewrite", "Writing the adapted screenplay one scene at a time, then checking every line against its source."],
];

const NICE: Record<string, string> = { analyse: "Analysis", extract: "Extraction", normalize: "Normalization", plan: "Adaptation plan", rewrite: "Rewrite" };
const label = (name: string) => NICE[name.split(" ")[0]] ?? name;

export function JobBanner({ job }: { job: JobInfo | null | undefined }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (job?.state !== "running") return;
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [job?.state]);

  if (!job || job.state === "done" || job.state === "idle") return null;

  if (job.state === "failed")
    return (
      <div role="alert" className="mb-6 flex gap-3 rounded-2xl border border-danger-line bg-danger-soft p-4 text-danger">
        <TriangleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
        <div className="text-sm">
          <p className="font-semibold">{label(job.name)} failed</p>
          <p className="mt-0.5 break-words text-danger/90">{job.error}</p>
          <p className="mt-1 text-danger/80">Nothing was lost: progress made before the failure is saved. Fix the cause and run it again; only unfinished work is redone.</p>
        </div>
      </div>
    );

  const elapsed = Math.max(0, Math.round(now - (job.started ?? now)));
  const text = MESSAGE.find(([k]) => job.name.startsWith(k))?.[1] ?? "Working…";
  return (
    <div role="status" aria-live="polite" className="mb-6 overflow-hidden rounded-2xl border border-info-line bg-info-soft">
      <div className="flex items-center gap-3 p-4 text-info">
        <Spinner className="size-5" />
        <div className="flex-1 text-sm">
          <p className="font-semibold">{label(job.name)} in progress</p>
          <p className="text-info/90">{text}</p>
        </div>
        <span className="text-right text-sm font-medium">
          {job.total ? <span className="tnum block">{job.progress}: {job.done} of {job.total}</span> : null}
          <span className="tnum block text-xs text-info/80">{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}</span>
        </span>
      </div>
      <div className="h-1 overflow-hidden bg-info/15">
        {job.total ? (
          <div className="h-full bg-info transition-[width] duration-500" style={{ width: `${Math.round(((job.done ?? 0) / job.total) * 100)}%` }} />
        ) : (
          <div className="h-full w-1/3 bg-info" style={{ animation: "indeterminate 1.6s ease-in-out infinite" }} />
        )}
      </div>
    </div>
  );
}
