"use client";

import { CircleHelp, RotateCcw, ShieldCheck } from "lucide-react";
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

type Guide = { means: string; check: string; reasons: string[] };

/** What each finding means, what to look at, and the reasons that legitimately make it fine. Plain words on purpose. */
const GUIDE: Record<string, Guide> = {
  PROP_HOLDER_MISMATCH: {
    means: "An object is held by one person at the end of a scene and by someone else at the start of the next, and nothing in the script says how it got there.",
    check: "Read the last lines of the earlier scene and the first lines of the later one. Does anyone hand the object over, or pick it up?",
    reasons: ["The handover happens off-screen between the scenes", "The script does show it, and the AI missed it", "It is deliberate: who has it is a mystery in the story"],
  },
  COSTUME_CHANGE_NO_REASON: {
    means: "A character wears different clothes in two scenes, and the script gives no reason for the change.",
    check: "How much time passes between the two scenes? Does the script mention changing, weather or an occasion?",
    reasons: ["Enough time passes that changing clothes is natural (a new day, a new place)", "The script does show or imply the change, and the AI missed it", "It is deliberate: the change means something in the story"],
  },
  PROP_NOT_SHOWN: {
    means: "An object that a character was holding is not mentioned in a scene where that character is on screen.",
    check: "Is the object still with them, only not mentioned? Or did they put it down?",
    reasons: ["They still have it; the script just does not mention it", "They put it away off-screen", "It is deliberate: the object is lost or hidden in the story"],
  },
  TRANSFER_SOURCE_MISMATCH: {
    means: "A handover says the object comes from someone who did not have it.",
    check: "Who really held the object just before the handover?",
    reasons: ["The AI misread who gave it (the script is correct)", "The object changed hands earlier, off-screen", "It is deliberate"],
  },
  TRANSFER_TARGET_MISMATCH: {
    means: "A handover says the object goes to someone, but afterwards a different person has it.",
    check: "Who really ends up with the object?",
    reasons: ["The AI misread who received it (the script is correct)", "It was passed on again off-screen", "It is deliberate"],
  },
  INJURY_HEAL_WITHOUT_INJURY: {
    means: "The script says a character is healed of an injury that was never shown.",
    check: "Was the injury mentioned in an earlier scene that the AI missed?",
    reasons: ["The injury happened before the script starts", "The AI missed the earlier injury (the script is correct)", "It is deliberate"],
  },
};
const GENERIC: Guide = {
  means: "The automatic check found two parts of the script that do not agree.",
  check: "Read the scenes listed below and decide whether they contradict each other.",
  reasons: ["The script is fine and the AI misread it", "It is deliberate in the story"],
};
const OTHER = "Something else (I will explain)";

const BAR = { error: "border-l-danger", warning: "border-l-warning", info: "border-l-info" } as const;

export function WarningCard({ w, n }: { w: Warning; n: string }) {
  const { id, demo } = useWorkspace();
  const act = useAct(id);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [detail, setDetail] = useState("");
  const [help, setHelp] = useState(false);
  const guide = GUIDE[w.code] ?? GENERIC;
  const note = reason === OTHER ? detail.trim() : [reason, detail.trim()].filter(Boolean).join(": ");

  const ack = () =>
    act.mutate(
      { run: () => api.acknowledge(id, w.id, note), ok: (r) => ((r as { approved?: boolean }).approved ? "Acknowledged. All approvals are in: the project is approved." : "Acknowledged.") },
      { onSuccess: () => { setOpen(false); setReason(""); setDetail(""); } },
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
              <Button variant="ghost" size="sm" aria-expanded={help} onClick={() => setHelp((v) => !v)}><CircleHelp aria-hidden /> How to resolve this</Button>
            </div>
          )}
        </div>
      )}
      {help && !w.acknowledged && (
        <div className="mt-4 space-y-3 rounded-xl bg-paper p-4 text-sm leading-relaxed">
          <p><strong>What this means.</strong> {guide.means}</p>
          <p><strong>What to check.</strong> {guide.check}</p>
          <div>
            <p className="mb-1.5 font-semibold">Read the scenes</p>
            <div className="flex flex-wrap gap-2">
              {w.affected_scene_ids.map((sid) => (
                <Link key={sid} href={`/projects/${id}/extract#scene-${sid}`} className={buttonVariants({ variant: "outline", size: "sm" })}>Scene {Number(sid.replace(/\D/g, ""))}</Link>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1.5 font-semibold">Then you have two choices</p>
            <ul className="list-disc space-y-1 pl-5">
              <li><strong>It is a real mistake in the screenplay:</strong> fix the screenplay and <Link href="/new" className="font-semibold text-primary underline underline-offset-2">upload it again</Link>. Scene details cannot be edited inside the app, so this is the only way to change them.</li>
              <li><strong>It is fine as it is:</strong> choose <em>Accept as intentional</em> and pick the reason. The reason is saved with the project.</li>
            </ul>
          </div>
        </div>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Accept this as intentional?</DialogTitle>
            <DialogDescription>{w.message}</DialogDescription>
          </DialogHeader>
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium">Why is this fine? (saved with the project)</legend>
            {[...guide.reasons, OTHER].map((r) => (
              <label key={r} className={cn("flex cursor-pointer items-start gap-2.5 rounded-lg border p-3 text-sm transition-colors", reason === r ? "border-primary bg-accent/60" : "hover:bg-muted/50")}>
                <input type="radio" name={`reason-${w.id}`} value={r} checked={reason === r} onChange={() => setReason(r)} className="mt-0.5 size-4 accent-[var(--primary)]" />
                <span>{r}</span>
              </label>
            ))}
          </fieldset>
          {reason && (
            <div className="space-y-1.5">
              <Label htmlFor={`ack-${w.id}`}>{reason === OTHER ? "Explain (required)" : "Add detail (optional)"}</Label>
              <Textarea id={`ack-${w.id}`} rows={2} value={detail} onChange={(e) => setDetail(e.target.value)} placeholder={reason === OTHER ? "Say why this is not a problem." : "e.g. Hari hands the letter back between scenes 2 and 4."} />
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={ack} disabled={!note || act.isPending}>{act.isPending && <Spinner />} Accept</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  );
}
