"use client";

import { Film, GitBranch, Image as ImageIcon, MessageSquareQuote, Scale, ScanText, UserRound } from "lucide-react";
import { useState } from "react";
import { BasisBadge, Chip, EmptyState, PageHeader, Pill } from "@/components/domain/bits";
import { useWorkspace } from "@/components/domain/workspace";
import { api } from "@/lib/api";
import { DIMENSION_LABEL, displayName, nativeName, sceneNo } from "@/lib/format";
import { rank } from "@/lib/stages";
import type { Asset, Project } from "@/lib/types";
import { cn } from "@/lib/utils";

function Step({ n, icon: Icon, title, hint, children, last }: { n: number; icon: React.ComponentType<{ className?: string }>; title: string; hint: string; children: React.ReactNode; last?: boolean }) {
  return (
    <li className="relative pl-14">
      <span className="absolute left-0 top-0 grid size-10 place-items-center rounded-full bg-primary text-primary-foreground"><Icon className="size-5" aria-hidden /></span>
      {!last && <span aria-hidden className="absolute left-5 top-12 -bottom-2 w-px bg-border" />}
      <div className="pb-8">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-primary">Step {n}</p>
        <h3 className="font-heading text-xl leading-tight">{title}</h3>
        <p className="mb-3 text-sm text-muted-foreground">{hint}</p>
        <div className="rounded-2xl border bg-card p-4 shadow-card">{children}</div>
      </div>
    </li>
  );
}

function Thumb({ id, a, caption }: { id: string; a?: Asset; caption: string }) {
  const ok = a && a.path && (a.status === "generated" || a.status === "stale");
  return (
    <figure className="w-36 shrink-0">
      <div className={cn("grid aspect-[3/4] place-items-center overflow-hidden rounded-xl border bg-muted/40", a?.kind === "scene_keyframe" && "aspect-[3/2]")}>
        {ok ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={api.assetUrl(id, a.id, `${a.spec_hash}-${a.attempts}`)} alt={caption} className="size-full object-cover" loading="lazy" />
        ) : <ImageIcon className="size-6 text-foreground/20" aria-hidden />}
      </div>
      <figcaption className="mt-1 text-xs text-muted-foreground">{caption}{a ? <> <Chip>{a.spec_hash.slice(0, 6)}</Chip></> : " (not generated)"}</figcaption>
    </figure>
  );
}

function CharacterTrace({ id, p, cid }: { id: string; p: Project; cid: string }) {
  const c = p.characters.find((x) => x.id === cid)!;
  const costumes = p.costumes.filter((k) => k.character_id === cid);
  const decisions = p.decisions.filter((d) => d.entity_id === cid || costumes.some((k) => k.id === d.entity_id));
  const lines = p.adapted_scenes.flatMap((a) => a.lines.filter((l) => l.character_id === cid).map((l) => ({ ...l, scene: a.source_scene_id })));
  const asset = (aid: string) => p.assets.find((a) => a.id === aid);
  const sceneIds = [...c.scene_ids].sort();
  const refIds = (p.assets.find((a) => a.id === `ASSET_KEYFRAME_${sceneIds[0]}`)?.reference_asset_ids) ?? [];
  return (
    <ol>
      <Step n={1} icon={ScanText} title="In the source" hint="How the screenplay refers to this person, before normalization.">
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <Pill tone="primary">{c.name}</Pill>{c.aliases.map((a) => <Pill key={a}>{a}</Pill>)}
          <span className="ml-2 text-muted-foreground">in</span>{sceneIds.map((s) => <Chip key={s}>{sceneNo(s)}</Chip>)}
        </div>
      </Step>
      <Step n={2} icon={UserRound} title="One canonical record" hint="Aliases merged into a single identity that every later step refers to.">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1"><Chip>{c.id}</Chip><span className="font-heading text-lg">{displayName(c, p.plan)}</span>{nativeName(c, p.plan) && <span className="gurmukhi text-lg text-primary">{nativeName(c, p.plan)}</span>}</div>
        <p className="mt-1 text-sm text-muted-foreground">{c.role_adapted || c.role}{c.physical_description ? ` · ${c.physical_description}` : ""}</p>
      </Step>
      <Step n={3} icon={Scale} title={`${decisions.length} adaptation decision${decisions.length === 1 ? "" : "s"}`} hint="Every choice made for this person (name, clothing, speech), with what it rests on.">
        {decisions.length === 0 ? <p className="text-sm text-muted-foreground">No decisions recorded.</p> : (
          <ul className="space-y-2">{decisions.slice(0, 6).map((d) => (
            <li key={d.id} className="flex flex-wrap items-center gap-2 text-sm">
              <Chip>{d.id}</Chip><Pill tone="primary">{DIMENSION_LABEL[d.dimension] ?? d.dimension}</Pill>
              <span className="text-muted-foreground">{d.original}</span><span aria-hidden>→</span><span className="min-w-0">{d.adapted}</span>
              <BasisBadge basis={d.basis} />{d.fact_ids.map((f) => <Chip key={f}>{f}</Chip>)}
            </li>))}
            {decisions.length > 6 && <li className="text-xs text-muted-foreground">…and {decisions.length - 6} more</li>}
          </ul>
        )}
      </Step>
      <Step n={4} icon={MessageSquareQuote} title={`${lines.length} rewritten line${lines.length === 1 ? "" : "s"}`} hint="Each adapted line keeps its source line number and the decisions behind it.">
        {lines.length === 0 ? <p className="text-sm text-muted-foreground">The screenplay has not been rewritten yet.</p> : (
          <ul className="space-y-3">{lines.filter((l) => l.kind === "dialogue").slice(0, 3).map((l, i) => (
            <li key={i} className="text-sm">
              <p className="gurmukhi text-base">{l.text}</p>
              {l.gloss && <p className="text-muted-foreground">{l.gloss}</p>}
              <p className="mt-0.5 flex flex-wrap gap-1.5 text-xs text-muted-foreground"><Chip>{sceneNo(l.scene)}</Chip>{l.source_line != null && <Chip>source line {l.source_line}</Chip>}{l.decision_ids?.map((d) => <Chip key={d}>{d}</Chip>)}</p>
            </li>))}
          </ul>
        )}
      </Step>
      <Step n={5} icon={Film} title="Images made from all of the above" hint="The reference image comes first; every later image is conditioned on it. The short code is the spec hash: if it changes, the image is out of date." last>
        <div className="flex gap-4 overflow-x-auto pb-1">
          <Thumb id={id} a={asset(`ASSET_CHARREF_${cid}`)} caption="Reference" />
          {costumes.map((k) => asset(`ASSET_COSTUME_${k.id}`)).filter(Boolean).map((a) => <Thumb key={a!.id} id={id} a={a} caption="Costume sheet" />)}
          {sceneIds.map((s) => <Thumb key={s} id={id} a={asset(`ASSET_KEYFRAME_${s}`)} caption={`${sceneNo(s)} keyframe`} />)}
        </div>
        {refIds.length > 0 && <p className="mt-2 text-xs text-muted-foreground">The {sceneNo(sceneIds[0])} keyframe was generated from: {refIds.map((r) => <Chip key={r} className="mr-1">{r.replace("ASSET_", "")}</Chip>)}</p>}
      </Step>
    </ol>
  );
}

function PropTrace({ id, p, pid }: { id: string; p: Project; pid: string }) {
  const prop = p.props.find((x) => x.id === pid)!;
  const scenes = [...p.scenes].sort((a, b) => a.number - b.number).filter((s) => prop.scene_ids.includes(s.scene_id));
  const name = (h: string | undefined) => (!h ? "?" : h.startsWith("@") ? h.slice(1) : displayName(p.characters.find((c) => c.id === h), p.plan) || h);
  const decisions = p.decisions.filter((d) => d.entity_id === pid);
  const warnings = p.warnings.filter((w) => w.entity_id === pid);
  return (
    <ol>
      <Step n={1} icon={ScanText} title="In the source" hint="Where the prop appears in the screenplay.">
        <div className="flex flex-wrap items-center gap-1.5 text-sm"><Pill tone="primary">{prop.name}</Pill><Chip>{prop.id}</Chip>{prop.scene_ids.map((s) => <Chip key={s}>{sceneNo(s)}</Chip>)}</div>
      </Step>
      <Step n={2} icon={GitBranch} title="Who holds it, scene by scene" hint="Tracked by code. A contradiction here is a continuity finding.">
        <ul className="space-y-1 text-sm">{scenes.map((s) => (
          <li key={s.scene_id} className="flex flex-wrap items-center gap-2"><Chip>{sceneNo(s.scene_id)}</Chip>
            <span>{name(s.prop_holder_start[pid])}</span><span aria-hidden>→</span><span>{name(s.prop_holder_end[pid])}</span></li>))}
        </ul>
        {warnings.map((w) => <p key={w.id} className="mt-3 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">{w.message}</p>)}
      </Step>
      <Step n={3} icon={Scale} title={`${decisions.length} adaptation decision${decisions.length === 1 ? "" : "s"}`} hint="How the object itself changes for the culture." >
        {decisions.length === 0 ? <p className="text-sm text-muted-foreground">Kept as in the source.</p> : (
          <ul className="space-y-2">{decisions.map((d) => <li key={d.id} className="flex flex-wrap items-center gap-2 text-sm"><Chip>{d.id}</Chip><span className="text-muted-foreground">{d.original}</span><span aria-hidden>→</span>{d.adapted}<BasisBadge basis={d.basis} /></li>)}</ul>
        )}
      </Step>
      <Step n={4} icon={Film} title="Shown in these keyframes" hint="The prop has no image of its own; it appears in the scene keyframes where it is present." last>
        <div className="flex gap-4 overflow-x-auto pb-1">{scenes.map((s) => <Thumb key={s.scene_id} id={id} a={p.assets.find((a) => a.id === `ASSET_KEYFRAME_${s.scene_id}`)} caption={`${sceneNo(s.scene_id)} keyframe`} />)}</div>
      </Step>
    </ol>
  );
}

export default function TracePage() {
  const { id, project: p } = useWorkspace();
  const [pick, setPick] = useState("");
  if (rank(p) < 2 || p.characters.length === 0)
    return (
      <>
        <PageHeader eyebrow="Trace" title="Follow one entity end to end" description="From the source text to the final image, every step that touched it." />
        <EmptyState icon={GitBranch} title="Nothing to trace yet" description="Run the analysis first; the trace follows a character or prop through every stage." />
      </>
    );
  const options = [...p.characters.map((c) => ({ id: c.id, label: c.name, kind: "Character" })), ...p.props.map((x) => ({ id: x.id, label: x.name, kind: "Prop" }))];
  const current = options.find((o) => o.id === pick) ?? options[0];
  return (
    <>
      <PageHeader eyebrow="Trace" title="Follow one entity end to end" description="Source text → one canonical record → adaptation decisions → rewritten lines → images. This is how an alias becomes a consistent person on screen." />
      <div role="tablist" aria-label="Entity" className="mb-8 flex flex-wrap gap-2">
        {options.map((o) => (
          <button key={o.id} role="tab" aria-selected={o.id === current.id} onClick={() => setPick(o.id)}
            className={cn("rounded-xl border px-3.5 py-1.5 text-sm font-medium transition-colors", o.id === current.id ? "border-primary bg-primary text-primary-foreground" : "bg-card hover:bg-muted")}>
            {o.label} <span className="text-xs opacity-70">{o.kind}</span>
          </button>
        ))}
      </div>
      {current.kind === "Character" ? <CharacterTrace id={id} p={p} cid={current.id} /> : <PropTrace id={id} p={p} pid={current.id} />}
    </>
  );
}
