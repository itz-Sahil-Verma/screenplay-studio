"use client";

import { CircleAlert, MapPin, Package, Shirt, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { sceneNo } from "@/lib/format";
import { warningNumber } from "@/lib/stages";
import type { Character, Costume, Location, Project, Prop } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CODE_TITLE } from "./warning-card";
import { Chip, Pill } from "./bits";

const short = (id: string) => sceneNo(id).replace("Scene ", "S");

function Card({ title, id, icon: Icon, children, actions }: { title: string; id: string; icon?: React.ComponentType<{ className?: string }>; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <li className="flex flex-col rounded-2xl border bg-card p-4 shadow-card">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="flex items-center gap-1.5 font-heading text-lg leading-snug">{Icon && <Icon className="size-4 shrink-0 text-primary" aria-hidden />}<span className="truncate">{title}</span></h3>
          <Chip>{id}</Chip>
        </div>
        {actions && <div className="flex shrink-0 gap-0.5">{actions}</div>}
      </div>
      <div className="mt-3 flex-1 space-y-2.5 text-sm">{children}</div>
    </li>
  );
}

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div><p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p><div className="mt-1 flex flex-wrap gap-1">{children}</div></div>
);

export function CharacterCard({ c, actions }: { c: Character; actions?: React.ReactNode }) {
  return (
    <Card title={c.name} id={c.id} actions={actions}>
      {c.role && <p className="text-muted-foreground">{c.age ? `${c.age} · ` : ""}{c.role}</p>}
      <Row label="Also called">{c.aliases.length ? c.aliases.map((a) => <Pill key={a}>{a}</Pill>) : <span className="text-muted-foreground">No other names</span>}</Row>
      <Row label="Appears in">{c.scene_ids.map((s) => <Chip key={s}>{short(s)}</Chip>)}</Row>
    </Card>
  );
}

export function PropCard({ p, prop, actions }: { p: Project; prop: Prop; actions?: React.ReactNode }) {
  const last = [...p.scenes].sort((a, b) => b.number - a.number).find((s) => s.prop_holder_end[prop.id]);
  const h = last?.prop_holder_end[prop.id];
  const holder = !h ? "not recorded" : h.startsWith("@") ? `left at ${h.slice(1)}` : p.characters.find((c) => c.id === h)?.name ?? h;
  return (
    <Card title={prop.name} id={prop.id} icon={Package} actions={actions}>
      <Row label={`Holder at the end${last ? ` (${short(last.scene_id)})` : ""}`}><span>{holder}</span></Row>
      <Row label="Scenes">{prop.scene_ids.map((s) => <Chip key={s}>{short(s)}</Chip>)}</Row>
    </Card>
  );
}

export function CostumeCard({ p, k }: { p: Project; k: Costume }) {
  const who = p.characters.find((c) => c.id === k.character_id);
  return (
    <Card title={who?.name ?? k.character_id} id={k.id} icon={Shirt}>
      <p>{(k.source_garments ?? k.garments) || <em className="text-muted-foreground">not described in the source</em>}</p>
      <Row label="Worn in">{k.scene_ids.map((s) => <Chip key={s}>{short(s)}</Chip>)}</Row>
      {k.change_reason && <p className="text-xs text-muted-foreground">Change reason: {k.change_reason}</p>}
    </Card>
  );
}

export function LocationCard({ l, actions }: { l: Location; actions?: React.ReactNode }) {
  return (
    <Card title={l.name} id={l.id} icon={MapPin} actions={actions}>
      {l.sub_locations.length > 0 && <Row label="Spaces">{l.sub_locations.map((x) => <Pill key={x}>{x}</Pill>)}</Row>}
      <Row label="Scenes">{l.scene_ids.map((s) => <Chip key={s}>{short(s)}</Chip>)}</Row>
    </Card>
  );
}

/** Everything that needs a person's eye, above the records it concerns. */
export function ProblemList({ p, continuityHref }: { p: Project; continuityHref: string }) {
  const failed = p.source_scenes.filter((s) => s.error);
  const open = p.warnings.filter((w) => w.severity !== "info" && !w.acknowledged);
  const total = failed.length + open.length + p.extraction_problems.length;
  if (total === 0)
    return <p className="mb-8 rounded-xl border border-success-line bg-success-soft px-4 py-3 text-sm text-success">Nothing needs attention in the extraction.</p>;
  return (
    <section aria-label="Problems" className="mb-8 rounded-2xl border border-warning-line bg-warning-soft p-4">
      <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-warning"><TriangleAlert className="size-4" aria-hidden /> {total} thing{total > 1 ? "s" : ""} to look at</p>
      <ul className="space-y-1.5 text-sm">
        {failed.map((s) => <li key={s.number} className="flex gap-2 text-danger"><CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />Scene {s.number} could not be read: {s.error}</li>)}
        {p.extraction_problems.map((m, i) => <li key={i} className="flex gap-2 text-warning"><CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />{m}</li>)}
        {open.map((w) => (
          <li key={w.id} className={cn("flex flex-wrap items-baseline gap-x-2", w.severity === "error" ? "text-danger" : "text-warning")}>
            <CircleAlert className="size-4 shrink-0 self-center" aria-hidden /><Chip>{warningNumber(p, w.id)}</Chip><span>{CODE_TITLE[w.code] ?? w.code}</span>
            <span className="text-xs opacity-80">scenes {w.affected_scene_ids.map((s) => s.replace(/\D/g, "").replace(/^0/, "")).join(" → ")}</span>
          </li>
        ))}
      </ul>
      {open.length > 0 && <Link href={continuityHref} className="mt-3 inline-block text-sm font-semibold text-warning underline underline-offset-2">Open the continuity report</Link>}
    </section>
  );
}
