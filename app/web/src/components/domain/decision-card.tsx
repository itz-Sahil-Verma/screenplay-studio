"use client";

import { ArrowRight, BookOpen, Check, Hand, MessageSquareQuote, Palette, Pencil, RotateCcw, UserRound, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { DIMENSION_LABEL } from "@/lib/format";
import { useAct } from "@/lib/hooks";
import type { Decision } from "@/lib/types";
import { cn } from "@/lib/utils";
import { BasisBadge, Chip, FlagBadge, Pill, Spinner, type Tone } from "./bits";
import { useWorkspace } from "./workspace";

const ICON = { verbal: MessageSquareQuote, non_verbal: Hand, character: UserRound, visual_world: Palette, story_world: BookOpen } as const;
const STATUS: Record<string, [string, Tone]> = { proposed: ["To review", "neutral"], accepted: ["Accepted", "success"], edited: ["Edited by you", "primary"], rejected: ["Rejected", "danger"] };

export function DecisionCard({ d, entityName }: { d: Decision; entityName?: string }) {
  const { id, demo } = useWorkspace();
  const act = useAct(id);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(d.adapted);
  const Icon = ICON[d.dimension as keyof typeof ICON] ?? BookOpen;
  const [statusLabel, statusTone] = STATUS[d.status] ?? STATUS.proposed;
  const set = (status: string, adapted?: string) => act.mutate({ run: () => api.reviewDecision(id, d.id, status, adapted) });

  return (
    <li className={cn("rounded-2xl border bg-card p-5 shadow-card", d.uncertain && "border-warning-line", d.status === "rejected" && "opacity-70")}>
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone="primary" icon={Icon}>{DIMENSION_LABEL[d.dimension] ?? d.dimension}</Pill>
        <BasisBadge basis={d.basis} />
        {d.uncertain && <FlagBadge reason={d.uncertain_reason} />}
        <span className="ml-auto flex items-center gap-2"><Chip>{d.id}</Chip><Pill tone={statusTone}>{statusLabel}</Pill></span>
      </div>
      {(entityName || d.entity_id) && <p className="mt-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">About {entityName ?? d.entity_id}</p>}
      <div className="mt-2 grid items-stretch gap-3 md:grid-cols-[1fr_auto_1.2fr]">
        <div className="rounded-xl bg-muted/60 p-3.5 text-sm leading-relaxed"><p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">In the source</p>{d.original}</div>
        <ArrowRight className="mx-auto hidden size-5 self-center text-primary md:block" aria-hidden />
        <div className="rounded-xl border border-primary/15 bg-accent/50 p-3.5 text-sm leading-relaxed"><p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-primary">Adapted</p>{d.adapted}</div>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground"><span className="font-medium text-foreground">Why: </span>{d.reason}</p>
      {d.uncertain && d.uncertain_reason && <p className="mt-2 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning"><strong>Flagged:</strong> {d.uncertain_reason}</p>}
      {d.fact_ids.length > 0 && <p className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">Pack facts: {d.fact_ids.map((f) => <Chip key={f}>{f}</Chip>)}</p>}
      {d.reviewer_note && <p className="mt-2 text-xs italic text-muted-foreground">Reviewer note: {d.reviewer_note}</p>}

      {!demo && (
        <div className="mt-4 flex flex-wrap gap-2 border-t pt-4">
          {d.status === "proposed" ? (
            <>
              <Button size="sm" disabled={act.isPending} onClick={() => set("accepted")}>{act.isPending ? <Spinner /> : <Check aria-hidden />} Accept</Button>
              <Button size="sm" variant="outline" onClick={() => { setText(d.adapted); setOpen(true); }}><Pencil aria-hidden /> Edit</Button>
              <Button size="sm" variant="ghost" disabled={act.isPending} onClick={() => set("rejected")}><X aria-hidden /> Reject</Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="ghost" disabled={act.isPending} onClick={() => set("proposed")}><RotateCcw aria-hidden /> Back to review</Button>
              <Button size="sm" variant="ghost" onClick={() => { setText(d.adapted); setOpen(true); }}><Pencil aria-hidden /> Edit</Button>
            </>
          )}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit this decision</DialogTitle>
            <DialogDescription>Your wording replaces the model’s, and is used when the screenplay is rewritten.</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5"><Label htmlFor={`d-${d.id}`}>Adapted</Label><Textarea id={`d-${d.id}`} rows={5} value={text} onChange={(e) => setText(e.target.value)} /></div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button disabled={!text.trim() || act.isPending} onClick={() => act.mutate({ run: () => api.reviewDecision(id, d.id, "edited", text), ok: () => "Decision updated" }, { onSuccess: () => setOpen(false) })}>{act.isPending && <Spinner />} Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  );
}

/** A decision that needs no attention (not flagged, already reviewed): one line, open it for the full reasoning.
 * Keeps the attention on the few decisions that are actually uncertain. */
export function CompactDecision({ d, entityName }: { d: Decision; entityName?: string }) {
  const [statusLabel, statusTone] = STATUS[d.status] ?? STATUS.proposed;
  return (
    <li>
      <details className="group rounded-xl border bg-card shadow-card open:shadow-lift">
        <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
          <Pill tone="primary">{DIMENSION_LABEL[d.dimension] ?? d.dimension}</Pill>
          <span className="min-w-0 flex-1 truncate text-sm">
            {entityName && <span className="font-medium">{entityName}: </span>}
            <span className="text-muted-foreground">{d.original}</span> <span aria-hidden>→</span> {d.adapted}
          </span>
          <BasisBadge basis={d.basis} />
          <Pill tone={statusTone}>{statusLabel}</Pill>
        </summary>
        <ul className="border-t p-3"><DecisionCard d={d} entityName={entityName} /></ul>
      </details>
    </li>
  );
}
