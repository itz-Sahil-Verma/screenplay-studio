"use client";

import { BookOpen, Flag, Hand, MessageSquareQuote, Volume2, Zap } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { CUE, SLUG, describeEvents, parseSourceDialogue } from "@/lib/source";
import { DIMENSION_LABEL } from "@/lib/format";
import type { AdaptedLine, AdaptedScene, Project, Scene } from "@/lib/types";
import { cn } from "@/lib/utils";
import { BasisBadge, Chip, FlagBadge, Pill } from "./bits";

/** The source screenplay in classic screenplay type: sluglines, centred speaker cues, indented speech. */
type Row = { kind: "gap" | "slug" | "cue" | "speech" | "action"; text: string };

function classify(text: string): Row[] {
  const lines = text.split("\n");
  const rows: Row[] = [];
  let inSpeech = false;
  lines.forEach((raw, i) => {
    const t = raw.trim();
    if (!t) { inSpeech = false; rows.push({ kind: "gap", text: "" }); }
    else if (SLUG.test(t)) rows.push({ kind: "slug", text: t });
    else if (!inSpeech && CUE.test(t) && lines[i + 1]?.trim()) { inSpeech = true; rows.push({ kind: "cue", text: t }); }
    else rows.push({ kind: inSpeech ? "speech" : "action", text: t });
  });
  return rows;
}

export function SourceScreenplay({ text }: { text: string }) {
  return (
    <div className="screenplay text-[13px] leading-[1.75]">
      {classify(text).map((r, i) =>
        r.kind === "gap" ? <div key={i} className="h-3" />
          : r.kind === "slug" ? <p key={i} className="mt-1 font-bold uppercase tracking-wide">{r.text}</p>
          : r.kind === "cue" ? <p key={i} className="mt-2 text-center font-bold">{r.text}</p>
          : <p key={i} className={cn(r.kind === "speech" && "mx-auto max-w-[28ch] text-left sm:max-w-[34ch]")}>{r.text}</p>)}
    </div>
  );
}

const KIND_ICON = { gesture: Hand, sound: Volume2, action: Zap, dialogue: MessageSquareQuote } as const;

export function AdaptedScreenplay({ p, a, gloss, onPick }: { p: Project; a: AdaptedScene; gloss: boolean; onPick: (l: AdaptedLine) => void }) {
  const nm = (id: string | null) => { const c = p.characters.find((x) => x.id === id); return c?.adapted_name_native || c?.name || ""; };
  return (
    <div className="gurmukhi text-[17px]">
      <p className="mb-3 font-bold">{a.heading}</p>
      {a.lines.map((l, i) => {
        const Icon = KIND_ICON[l.kind as keyof typeof KIND_ICON] ?? Zap;
        return (
          <div key={i} className="mb-1">
            <button type="button" onClick={() => onPick(l)} title="Show where this line comes from"
              className={cn("group block w-full rounded-lg px-2 py-0.5 text-left transition-colors hover:bg-accent focus-visible:bg-accent",
                l.kind === "dialogue" && "text-center", l.kind === "sound" && "italic text-muted-foreground", l.kind === "gesture" && "text-foreground/90")}>
              {l.kind === "dialogue" && <span className="block text-sm font-bold uppercase tracking-wide text-primary">{nm(l.character_id)}</span>}
              <span className={cn(l.kind === "dialogue" && "mx-auto inline-block max-w-[30ch] text-left")}>
                {l.kind === "sound" ? `(${l.text})` : l.text}
                {l.uncertain && <Flag className="ml-1.5 inline size-3.5 align-baseline text-warning" aria-label="The model is unsure of this line" />}
                <Icon className="ml-1.5 inline size-3 align-baseline text-transparent group-hover:text-muted-foreground" aria-hidden />
              </span>
              {gloss && l.gloss && <span className="mt-0.5 block font-sans text-[12.5px] italic leading-snug text-muted-foreground">{l.gloss}</span>}
            </button>
          </div>
        );
      })}
    </div>
  );
}

/** Everything behind one adapted line: its source line, the events it shows, the decisions and the pack facts. */
export function TraceDialog({ p, scene, line, onClose }: { p: Project; scene: Scene | undefined; line: AdaptedLine | null; onClose: () => void }) {
  if (!line || !scene) return <Dialog open={false} onOpenChange={onClose}><DialogContent /></Dialog>;
  const src = parseSourceDialogue(scene.source_text);
  const source = line.source_line ? src[line.source_line - 1] : undefined;
  const events = describeEvents(p, scene);
  const decisions = line.decision_ids.map((id) => p.decisions.find((d) => d.id === id)).filter(Boolean) as Project["decisions"];
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Where this line comes from</DialogTitle>
          <DialogDescription>Every adapted line is traced to a source line and to the decisions that shaped it.</DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          <div className="rounded-xl bg-adapted p-4">
            <p className="gurmukhi text-lg">{line.text}</p>
            {line.gloss && <p className="mt-1 text-sm italic text-muted-foreground">{line.gloss}</p>}
          </div>
          <section>
            <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Source</h4>
            {source ? (
              <div className="rounded-xl bg-muted/60 p-3.5"><p className="mb-1 text-xs text-muted-foreground">Adapts source dialogue line {line.source_line} in {`Scene ${scene.number}`}, spoken by <strong className="text-foreground">{source.speaker}</strong></p><p className="screenplay text-[13px]">{source.text}</p></div>
            ) : (
              <p className="rounded-xl bg-muted/60 p-3.5 text-sm text-muted-foreground">{line.kind === "dialogue" ? "No source line: this dialogue was added because an accepted decision called for it (see below)." : "An action, gesture or sound line: it dramatises the scene rather than translating a single source line."}</p>
            )}
          </section>
          {line.event_ids.length > 0 && (
            <section>
              <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Story events it shows</h4>
              <ul className="space-y-1 text-sm">{line.event_ids.map((n) => <li key={n} className="flex items-start gap-2"><Chip>{n}</Chip>{events[n - 1] ?? "unknown event"}</li>)}</ul>
            </section>
          )}
          <section>
            <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Decisions behind it</h4>
            {decisions.length === 0 ? <p className="text-sm text-muted-foreground">None cited: a direct rendering of the source in the chosen dialect.</p> : (
              <ul className="space-y-2.5">
                {decisions.map((d) => (
                  <li key={d.id} className="rounded-xl border p-3.5">
                    <div className="mb-1.5 flex flex-wrap items-center gap-1.5"><Chip>{d.id}</Chip><Pill tone="primary" icon={BookOpen}>{DIMENSION_LABEL[d.dimension]}</Pill><BasisBadge basis={d.basis} />{d.uncertain && <FlagBadge reason={d.uncertain_reason} />}</div>
                    <p className="text-sm"><span className="text-muted-foreground">{d.original}</span> → <strong className="font-medium">{d.adapted}</strong></p>
                    <p className="mt-1 text-xs text-muted-foreground">{d.reason}</p>
                    {d.fact_ids.length > 0 && <p className="mt-1.5 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">Pack facts: {d.fact_ids.map((f) => <Chip key={f}>{f}</Chip>)}</p>}
                  </li>
                ))}
              </ul>
            )}
          </section>
          {line.uncertain && <p className="rounded-xl bg-warning-soft p-3.5 text-sm text-warning"><strong>The model is unsure of this line.</strong> {line.note}</p>}
        </div>
      </DialogContent>
    </Dialog>
  );
}
