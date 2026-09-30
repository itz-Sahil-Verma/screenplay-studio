"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { buttonVariants } from "@/components/ui/button";
import { buildSteps } from "@/lib/stages";
import type { Project } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Back / Continue at the foot of every step, so nobody has to go back up to the stepper to move on.
 * Continue is the primary action once the current step is done; before that it stays available but quiet,
 * and is disabled only when the next step is locked behind an approval. */
export function StepNav({ id, project }: { id: string; project: Project }) {
  const path = usePathname();
  const steps = buildSteps(project);
  const base = `/projects/${id}`;
  const i = steps.findIndex((s) => path === base + s.path);
  if (i < 0) return null;
  const cur = steps[i], prev = steps[i - 1], next = steps[i + 1];
  const running = project.job?.state === "running";
  const ready = cur.state === "done" && !running;
  const blocked = next?.state === "locked";
  return (
    <nav aria-label="Step navigation" className="sticky bottom-0 z-30 -mx-4 mt-12 flex items-center justify-between gap-3 border-t bg-paper/90 px-4 py-3 backdrop-blur supports-[backdrop-filter]:bg-paper/80 sm:-mx-6 sm:px-6">
      {prev ? (
        <Link href={base + prev.path} className={buttonVariants({ variant: "outline", size: "lg" })}><ArrowLeft aria-hidden /> Back: {prev.label}</Link>
      ) : <span />}
      {next ? (
        blocked ? (
          <span className="flex items-center gap-3 text-sm text-muted-foreground">
            {next.hint}
            <span aria-disabled className={cn(buttonVariants({ size: "lg" }), "pointer-events-none opacity-50")}>Next: {next.label} <ArrowRight aria-hidden /></span>
          </span>
        ) : (
          <Link href={base + next.path} className={buttonVariants({ size: "lg", variant: ready ? "default" : "outline" })}>
            {ready ? "Continue" : "Next"}: {next.label} <ArrowRight aria-hidden />
          </Link>
        )
      ) : <span />}
    </nav>
  );
}
