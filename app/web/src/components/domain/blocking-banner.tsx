"use client";

import { OctagonAlert } from "lucide-react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import type { Project } from "@/lib/types";

/** Shown wherever a person is about to approve: continuity contradictions are a separate check from the cultural
 * decisions, and they stop approval until accepted with a reason (or the script is fixed and uploaded again). */
export function BlockingBanner({ id, project }: { id: string; project: Project }) {
  const n = project.blocking_warning_ids.length;
  if (n === 0) return null;
  return (
    <div role="alert" className="mb-6 flex flex-wrap items-center gap-3 rounded-2xl border border-danger-line bg-danger-soft p-4 text-sm text-danger">
      <OctagonAlert className="size-5 shrink-0" aria-hidden />
      <p className="min-w-0 flex-1">
        <strong>{n} continuity finding{n > 1 ? "s" : ""} block{n > 1 ? "" : "s"} approval.</strong> Reviewing the decisions below does not clear {n > 1 ? "them" : "it"}: they are contradictions in the screenplay itself, checked separately.
      </p>
      <Link href={`/projects/${id}/continuity`} className={buttonVariants({ size: "sm", variant: "outline" }) + " bg-card"}>Resolve {n > 1 ? "them" : "it"}</Link>
    </div>
  );
}
