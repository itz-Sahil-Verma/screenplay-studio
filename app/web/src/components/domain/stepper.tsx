"use client";

import { Check, House, Lock, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { buildSteps, progress, type StepState } from "@/lib/stages";
import type { Project } from "@/lib/types";
import { Spinner } from "./bits";

function Marker({ state, n }: { state: StepState; n: number }) {
  const base = "grid size-8 shrink-0 place-items-center rounded-full text-sm font-semibold transition-colors";
  if (state === "done") return <span className={cn(base, "bg-success text-white")}><Check className="size-4" aria-hidden /><span className="sr-only">Done</span></span>;
  if (state === "running") return <span className={cn(base, "bg-info-soft text-info ring-2 ring-info/40")}><Spinner /><span className="sr-only">Running</span></span>;
  if (state === "failed") return <span className={cn(base, "bg-danger text-white")}><TriangleAlert className="size-4" aria-hidden /><span className="sr-only">Failed</span></span>;
  if (state === "locked") return <span className={cn(base, "bg-muted text-muted-foreground")}><Lock className="size-3.5" aria-hidden /><span className="sr-only">Locked</span></span>;
  if (state === "current") return <span className={cn(base, "bg-primary text-primary-foreground ring-4 ring-primary/15")}>{n}</span>;
  return <span className={cn(base, "border-2 border-border bg-card text-muted-foreground")}>{n}</span>;
}

/** The whole pipeline at a glance: what is done, what is next, what is locked behind an approval. */
export function Stepper({ id, project }: { id: string; project: Project }) {
  const path = usePathname();
  const steps = buildSteps(project);
  const base = `/projects/${id}`;
  return (
    <nav aria-label="Workflow" className="mb-6 overflow-x-auto rounded-2xl border bg-card p-2 shadow-card">
      <ol className="flex min-w-[1000px] items-stretch">
        <li className="flex shrink-0 items-center">
          <Link
            href={base}
            aria-current={path === base ? "page" : undefined}
            className={cn("flex items-center gap-2.5 rounded-xl px-2.5 py-2.5 transition-colors hover:bg-muted", path === base && "bg-accent hover:bg-accent")}
          >
            <span className="grid size-8 shrink-0 place-items-center rounded-full border-2 border-border bg-card text-muted-foreground"><House className="size-4" aria-hidden /></span>
            <span className="min-w-0">
              <span className={cn("block text-sm font-semibold leading-tight", path === base && "text-accent-foreground")}>Overview</span>
              <span className="block truncate text-xs text-muted-foreground">{progress(project)}% done</span>
            </span>
          </Link>
          <span aria-hidden className="mx-0.5 h-px w-3 shrink-0 bg-border" />
        </li>
        {steps.map((s, i) => {
          const href = base + s.path;
          const viewing = path === href;
          return (
            <li key={s.key} className="flex min-w-0 flex-1 items-center">
              <Link
                href={href}
                aria-current={viewing ? "page" : undefined}
                className={cn("flex w-full min-w-0 items-center gap-2.5 rounded-xl px-2.5 py-2.5 transition-colors hover:bg-muted", viewing && "bg-accent hover:bg-accent", s.state === "locked" && "opacity-70")}
              >
                <Marker state={s.state} n={i + 1} />
                <span className="min-w-0">
                  <span className={cn("block text-sm font-semibold leading-tight", viewing && "text-accent-foreground")}>{s.label}</span>
                  <span className="line-clamp-2 block text-xs leading-snug text-muted-foreground" title={s.hint}>{s.hint}</span>
                </span>
              </Link>
              {i < steps.length - 1 && <span aria-hidden className={cn("mx-0.5 h-px w-3 shrink-0", s.state === "done" ? "bg-success/50" : "bg-border")} />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
