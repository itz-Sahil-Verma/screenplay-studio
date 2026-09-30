"use client";

import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, CheckCircle2, CircleAlert, LockOpen, ScrollText, Shirt, UserRound, Undo2 } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, Pill, Section, Spinner } from "@/components/domain/bits";
import { WarningCard } from "@/components/domain/warning-card";
import { useWorkspace } from "@/components/domain/workspace";
import { api } from "@/lib/api";
import { useAct } from "@/lib/hooks";
import { rank, warningNumber } from "@/lib/stages";
import type { ApprovalKey } from "@/lib/types";
import { cn } from "@/lib/utils";

const GATES: { key: ApprovalKey; title: string; icon: React.ComponentType<{ className?: string }>; text: string; page: string }[] = [
  { key: "characters", title: "Characters", icon: UserRound, text: "Each person is one record, with a name, role and appearance that fit the culture.", page: "/plan" },
  { key: "costumes", title: "Costumes", icon: Shirt, text: "One costume per look, and a story reason for every change of clothes.", page: "/plan" },
  { key: "plan", title: "Adaptation plan", icon: ScrollText, text: "Every decision reviewed. Flagged ones need an explicit accept or your own edit.", page: "/plan" },
];

function Gate({ g }: { g: (typeof GATES)[number] }) {
  const { id, project: p, demo } = useWorkspace();
  const act = useAct(id);
  const done = p.approval[g.key];
  const signature = [p.status, p.decisions.map((d) => d.status[0]).join(""), p.plan?.problems.length, p.plan?.stale_scenes.length, p.warnings.filter((w) => w.acknowledged).length, p.user_edits.length].join("|");
  const { data, isLoading } = useQuery({ queryKey: ["blockers", id, g.key, signature], queryFn: () => api.blockers(id, g.key), enabled: !done });
  // 62 separate "DEC001 has not been reviewed" lines say nothing more than "62 decisions have not been reviewed"
  const raw = data?.blockers ?? [];
  const unreviewed = raw.filter((b) => /^DEC\d+ has not been reviewed$/.test(b));
  const blockers = [...(unreviewed.length ? [`${unreviewed.length} decision${unreviewed.length > 1 ? "s have" : " has"} not been reviewed yet`] : []), ...raw.filter((b) => !unreviewed.includes(b))];
  const ready = !done && !isLoading && blockers.length === 0;
  const Icon = g.icon;

  return (
    <li className={cn("flex flex-col rounded-2xl border bg-card p-5 shadow-card", done && "border-success-line")}>
      <div className="flex items-start gap-3">
        <span className={cn("grid size-10 shrink-0 place-items-center rounded-xl", done ? "bg-success-soft text-success" : "bg-accent text-primary")}><Icon className="size-5" aria-hidden /></span>
        <div className="flex-1"><h3 className="font-heading text-xl">{g.title}</h3><p className="text-sm text-muted-foreground">{g.text}</p></div>
        {done ? <Pill tone="success" icon={CheckCircle2}>Approved</Pill> : ready ? <Pill tone="info">Ready</Pill> : <Pill tone="warning" icon={CircleAlert}>Blocked</Pill>}
      </div>
      <div className="mt-4 flex-1">
        {!done && isLoading && <Skeleton className="h-16 w-full" />}
        {!done && blockers.length > 0 && (
          <div className="rounded-xl bg-warning-soft p-3.5">
            <p className="mb-1.5 text-sm font-semibold text-warning">{blockers.length} thing{blockers.length > 1 ? "s" : ""} to resolve</p>
            <ul className="list-disc space-y-1 pl-5 text-sm text-warning/95">{blockers.slice(0, 6).map((b, i) => <li key={i}>{b}</li>)}{blockers.length > 6 && <li>…and {blockers.length - 6} more</li>}</ul>
            <Link href={`/projects/${id}${g.page}`} className="mt-2 inline-block text-sm font-semibold text-warning underline underline-offset-2">Go and resolve</Link>
          </div>
        )}
        {ready && <p className="rounded-xl bg-success-soft p-3.5 text-sm text-success">Nothing stands in the way. Approving records that you have read and accepted this.</p>}
      </div>
      {!demo && (
        <div className="mt-4 border-t pt-4">
          {done ? (
            <Button variant="ghost" size="sm" disabled={act.isPending} onClick={() => act.mutate({ run: () => api.unapprove(id, g.key), ok: () => `${g.title} approval withdrawn` })}><Undo2 aria-hidden /> Withdraw approval</Button>
          ) : (
            <Button disabled={!ready || act.isPending} onClick={() => act.mutate({ run: () => api.approve(id, g.key), ok: (r) => ((r as { approved?: boolean }).approved ? "All approvals are in. The project is approved." : `${g.title} approved`) })}>{act.isPending ? <Spinner /> : <BadgeCheck aria-hidden />} Approve {g.title.toLowerCase()}</Button>
          )}
        </div>
      )}
    </li>
  );
}

export default function ApprovePage() {
  const { id, project: p } = useWorkspace();
  const r = rank(p);
  const approvedAll = r >= 4;
  const gatesDone = Object.values(p.approval).every(Boolean);

  return (
    <>
      <PageHeader eyebrow="Step 4" title="Approval gates" description="Nothing expensive or hard to undo happens until you approve. Each gate lists exactly what stands in the way; any later edit closes them again." />
      {r < 3 ? (
        <p className="rounded-2xl border border-dashed bg-card/60 p-8 text-center text-muted-foreground">Approvals open once the adaptation plan exists. <Link href={`/projects/${id}`} className="font-semibold text-primary underline underline-offset-2">Go to the overview</Link>.</p>
      ) : (
        <>
          <div className={cn("mb-6 flex items-start gap-4 rounded-2xl border p-5", approvedAll ? "border-success-line bg-success-soft text-success" : "bg-card shadow-card")}>
            <span className={cn("grid size-11 shrink-0 place-items-center rounded-xl", approvedAll ? "bg-success text-white" : "bg-accent text-primary")}>{approvedAll ? <LockOpen className="size-5" aria-hidden /> : <BadgeCheck className="size-5" aria-hidden />}</span>
            <div className="flex-1">
              <h2 className="font-heading text-xl">{approvedAll ? "Approved: rewriting and image generation are unlocked" : "Waiting for your approval"}</h2>
              <p className={cn("mt-1 text-sm", approvedAll ? "text-success/90" : "text-muted-foreground")}>
                {approvedAll ? "The approved plan has been applied to the character, costume and place records." :
                  gatesDone && p.blocking_warning_ids.length ? `All three gates are approved, but ${p.blocking_warning_ids.length} blocking continuity finding(s) are unresolved. Fix them or accept them with a reason.` :
                    `${Object.values(p.approval).filter(Boolean).length} of 3 approved. All three, plus no unresolved blocking continuity finding, open the next step.`}
              </p>
            </div>
          </div>
          {!approvedAll && p.blocking_warning_ids.length > 0 && (
            <Section title={`Findings that block approval (${p.blocking_warning_ids.length})`} description="Contradictions in the screenplay itself. Accept each one with a reason, or fix the screenplay and upload it again. Cultural decisions do not clear them.">
              <ul className="space-y-3">
                {p.warnings.filter((w) => p.blocking_warning_ids.includes(w.id)).map((w) => <WarningCard key={w.id} w={w} n={warningNumber(p, w.id)} />)}
              </ul>
            </Section>
          )}
          <ul className="grid gap-4 lg:grid-cols-3">{GATES.map((g) => <Gate key={g.key} g={g} />)}</ul>
        </>
      )}
    </>
  );
}
