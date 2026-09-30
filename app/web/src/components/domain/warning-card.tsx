"use client";

import { RotateCcw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useAct } from "@/lib/hooks";
import type { Warning } from "@/lib/types";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { Chip, SceneSpan, SeverityBadge, Spinner } from "./bits";
import { useWorkspace } from "./workspace";

export const CODE_TITLE: Record<string, string> = {
  PROP_HOLDER_MISMATCH: "A prop changes hands with no explanation",
  COSTUME_CHANGE_NO_REASON: "A costume changes with no reason",
  PROP_NOT_SHOWN: "A prop disappears while its holder is on screen",
  TRANSFER_SOURCE_MISMATCH: "A handover starts from the wrong person",
  TRANSFER_TARGET_MISMATCH: "A handover ends with the wrong person",
  INJURY_ACTIVE: "An injury must stay visible",
  INJURY_HEAL_WITHOUT_INJURY: "Healed of an injury that never happened",
  SCENE_MISSING: "A source scene is missing",
  SCENE_GAP: "Scene numbers have a gap",
  MISSING_LOCATION: "A scene has no location",
  NO_CHARACTERS: "A scene has no characters",
};

const BAR = { error: "border-l-danger", warning: "border-l-warning", info: "border-l-info" } as const;

export function WarningCard({ w, n }: { w: Warning; n: string }) {
  const { id, demo } = useWorkspace();
  const act = useAct(id);
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");

  const ack = () =>
    act.mutate(
      { run: () => api.acknowledge(id, w.id, note.trim()), ok: (r) => ((r as { approved?: boolean }).approved ? "Acknowledged. All approvals are in: the project is approved." : "Acknowledged.") },
      { onSuccess: () => { setOpen(false); setNote(""); } },
    );

  return (
    <li className={cn("rounded-2xl border border-l-4 bg-card p-5 shadow-card", BAR[w.severity as keyof typeof BAR])}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <Chip className="text-xs">{n}</Chip>
        <h3 className="font-heading text-lg leading-snug">{CODE_TITLE[w.code] ?? w.code}</h3>
        <span className="ml-auto"><SeverityBadge severity={w.severity} acknowledged={w.acknowledged} /></span>
      </div>
      <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        <div><dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Type</dt><dd className="mt-0.5 font-mono text-xs">{w.code}</dd></div>
        <div><dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Affected scenes</dt><dd className="mt-0.5"><SceneSpan ids={w.affected_scene_ids} /></dd></div>
        <div><dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">About</dt><dd className="mt-0.5">{w.entity_id ? <Chip>{w.entity_id}</Chip> : "–"}</dd></div>
        <div><dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Status</dt><dd className="mt-0.5">{w.acknowledged ? "Accepted as intentional" : w.severity === "info" ? "For information" : "Unresolved"}</dd></div>
      </dl>
      <p className="mt-3 text-[15px] leading-relaxed">{w.message}</p>
      {w.acknowledged && (
        <p className="mt-3 flex items-start gap-2 rounded-lg bg-success-soft p-3 text-sm text-success">
          <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden /><span><strong>Accepted as intentional:</strong> {w.ack_note}</span>
        </p>
      )}
      {!demo && w.severity !== "info" && (
        <div className="mt-4">
          {w.acknowledged ? (
            <Button variant="ghost" size="sm" onClick={() => act.mutate({ run: () => api.acknowledge(id, w.id, "", false), ok: () => "Acknowledgement removed. Approval steps back." })}><RotateCcw aria-hidden /> Undo</Button>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => setOpen(true)}><ShieldCheck aria-hidden /> Accept as intentional</Button>
              <Link href={`/projects/${id}/extract`} className={buttonVariants({ variant: "ghost", size: "sm" })}>Edit the record</Link>
            </div>
          )}
        </div>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Accept this as intentional?</DialogTitle>
            <DialogDescription>{w.message}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor={`ack-${w.id}`}>Why is this fine? (required, kept with the project)</Label>
            <Textarea id={`ack-${w.id}`} rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Hari hands the letter back off-screen between scenes 2 and 4." />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={ack} disabled={!note.trim() || act.isPending}>{act.isPending && <Spinner />} Accept</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  );
}
