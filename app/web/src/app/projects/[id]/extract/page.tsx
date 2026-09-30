"use client";

import { ChevronDown, CircleAlert, ScanText, Shirt } from "lucide-react";
import { EmptyState, PageHeader, Pill, Section } from "@/components/domain/bits";
import { CharacterCard, CostumeCard, LocationCard, ProblemList, PropCard } from "@/components/domain/entity-cards";
import { EditCharacterButton, MergeButton } from "@/components/domain/edit-dialogs";
import { RunButton } from "@/components/domain/run-button";
import { useWorkspace } from "@/components/domain/workspace";
import { rank } from "@/lib/stages";
import type { Project, Scene } from "@/lib/types";

const label = (s: string) => s.replaceAll("_", " ");
/** The model sometimes shouts ("KITCHEN"); show it in sentence case. */
const tidy = (s: string) => (s && s === s.toUpperCase() ? s.charAt(0) + s.slice(1).toLowerCase() : s);

function Facts({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{title}</dt>
      <dd className="mt-1 flex flex-wrap gap-1">{items.map((x, i) => <Pill key={i}>{x}</Pill>)}</dd>
    </div>
  );
}

function SceneCard({ p, s }: { p: Project; s: Scene }) {
  const name = (id: string) => p.characters.find((c) => c.id === id)?.name ?? id;
  const prop = (id: string) => p.props.find((x) => x.id === id)?.name ?? id;
  const garment = (id: string) => p.costumes.find((c) => c.id === id)?.source_garments ?? p.costumes.find((c) => c.id === id)?.garments ?? "";
  const loc = p.locations.find((l) => l.id === s.location_id);
  const holder = (h: string) => (h.startsWith("@") ? h.slice(1) : name(h));
  const prod = s.production;
  const warns = p.warnings.filter((w) => s.continuity_warnings.includes(w.id));
  const targeted = typeof window !== "undefined" && window.location.hash === `#scene-${s.scene_id}`;  // a link from a finding opens this scene
  return (
    <details
      id={`scene-${s.scene_id}`}
      open={targeted || undefined}
      ref={(el) => { if (el && targeted && !el.dataset.scrolled) { el.dataset.scrolled = "1"; el.scrollIntoView({ block: "start" }); } }}
      className="group scroll-mt-28 rounded-2xl border bg-card shadow-card open:shadow-lift"
    >
      <summary className="flex cursor-pointer list-none items-center gap-3 p-4 [&::-webkit-details-marker]:hidden">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent font-heading text-lg text-primary">{s.number}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{loc?.name ?? s.location_id}{s.sub_location ? ` · ${tidy(s.sub_location)}` : ""}</span>
          <span className="block truncate text-sm text-muted-foreground">{s.int_ext} · {tidy(s.time) || "time not stated"}{s.mood ? ` · ${tidy(s.mood)}` : ""}</span>
        </span>
        <span className="hidden gap-1.5 sm:flex">
          <Pill>{s.characters.length} characters</Pill>
          {warns.length > 0 && <Pill tone={warns.some((w) => w.severity === "error" && !w.acknowledged) ? "danger" : "warning"} icon={CircleAlert} title="Continuity findings touching this scene">{warns.length}</Pill>}
        </span>
        <ChevronDown className="size-5 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="grid gap-6 border-t p-5 lg:grid-cols-2">
        <div className="space-y-5">
          {s.summary && <p className="text-sm leading-relaxed">{s.summary}</p>}
          <dl className="grid gap-3 text-sm">
            {s.dramatic_purpose && <div><dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Dramatic purpose</dt><dd className="mt-0.5">{s.dramatic_purpose}</dd></div>}
            {s.emotional_change && <div><dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Emotional change</dt><dd className="mt-0.5">{s.emotional_change}</dd></div>}
          </dl>
          <div>
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">State after the scene</h4>
            <ul className="space-y-2">
              {s.characters.map((cid) => {
                const st = s.states[cid];
                const worn = garment(s.costumes[cid] ?? "");
                return (
                  <li key={cid} className="rounded-xl bg-paper p-3 text-sm">
                    <p className="font-medium">{name(cid)}{worn && <span className="ml-2 inline-flex items-center gap-1 font-normal text-muted-foreground"><Shirt className="size-3.5" aria-hidden />{worn}</span>}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {st?.carrying.map((x) => <Pill key={x} tone="info">holds {prop(x)}</Pill>)}
                      {st?.injuries.map((x) => <Pill key={x} tone="danger">{x}</Pill>)}
                      {st?.knows.map((x) => <Pill key={x} tone="primary">knows: {x}</Pill>)}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
        <div className="space-y-5">
          <div>
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Props: who holds what</h4>
            {Object.keys({ ...s.prop_holder_start, ...s.prop_holder_end }).length === 0 ? <p className="text-sm text-muted-foreground">None recorded.</p> : (
              <ul className="space-y-1 text-sm">
                {Object.keys({ ...s.prop_holder_start, ...s.prop_holder_end }).map((pid) => (
                  <li key={pid} className="flex flex-wrap items-center gap-1.5"><span className="font-medium">{prop(pid)}</span>
                    <span className="text-muted-foreground">{s.prop_holder_start[pid] ? holder(s.prop_holder_start[pid]) : "in the scene"} → {s.prop_holder_end[pid] ? holder(s.prop_holder_end[pid]) : "unknown"}</span></li>
                ))}
              </ul>
            )}
          </div>
          {s.state_changes.length > 0 && (
            <div>
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Events</h4>
              <ul className="space-y-1 text-sm">{s.state_changes.map((e, i) => <li key={i}><span className="font-medium">{name(e.character_id)}</span> <span className="text-muted-foreground">{label(e.kind)}:</span> {e.kind.startsWith("prop") ? prop(e.item) : e.item}{e.to_character_id ? ` → ${name(e.to_character_id)}` : ""}</li>)}</ul>
            </div>
          )}
          <dl className="grid gap-3">
            <Facts title="Set" items={prod.set_dressing} /><Facts title="Food" items={prod.food} /><Facts title="Vehicles" items={prod.vehicles} />
            <Facts title="Animals" items={prod.animals} /><Facts title="Extras" items={prod.extras} /><Facts title="Rituals" items={prod.rituals} />
            <Facts title="Gestures" items={prod.gestures} /><Facts title="Sound" items={prod.sound_music} />
          </dl>
        </div>
      </div>
    </details>
  );
}

export default function ExtractPage() {
  const { id, project: p, demo } = useWorkspace();
  const r = rank(p);

  if (r < 2)
    return (
      <>
        <PageHeader eyebrow="Step 1" title="Extraction review" description="The screenplay, read into structured records. Anything the model claims that is not in the text is rejected." />
        {(p.job?.state === "running" || p.source_scenes.some((s) => s.extraction || s.error)) && (
          <ul className="mb-6 space-y-2">
            {p.source_scenes.map((s) => (
              <li key={s.number} className="flex items-center gap-3 rounded-xl border bg-card p-3.5 shadow-card">
                <span className="grid size-8 place-items-center rounded-lg bg-muted font-heading">{s.number}</span>
                <span className="flex-1 truncate text-sm font-medium">{s.heading || "(no heading)"}</span>
                {s.error ? <Pill tone="danger" icon={CircleAlert} title={s.error}>Failed</Pill> : s.extraction ? <Pill tone="success">Extracted</Pill> : <Pill>Waiting</Pill>}
              </li>
            ))}
          </ul>
        )}
        <EmptyState icon={ScanText} title={r === 0 ? "Not extracted yet" : "Not normalized yet"} description="Run the next step to see scenes, characters and props here."
          action={!demo && <RunButton stage={r === 0 ? "extract" : "normalize"} size="lg">{r === 0 ? "Extract scenes" : "Normalize and check continuity"}</RunButton>} />
      </>
    );

  const chars = p.characters.map((c) => ({ id: c.id, name: c.name }));
  return (
    <>
      <PageHeader eyebrow="Step 1" title="Extraction review" description="Check what was found. Fix a wrong name or merge two records that are the same thing; only the affected scenes are marked for re-generation." />

      <ProblemList p={p} continuityHref={`/projects/${id}/continuity`} />

      <Section title={`Cast (${p.characters.length})`} description="One record per person. Aliases are merged into the main name.">
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {p.characters.map((c) => <CharacterCard key={c.id} c={c} actions={!demo && <><EditCharacterButton character={c} /><MergeButton kind="character" record={c} options={chars} /></>} />)}
        </ul>
      </Section>

      <Section title={`Props (${p.props.length})`} description="One record each, tracked from scene to scene.">
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {p.props.map((x) => <PropCard key={x.id} p={p} prop={x} actions={!demo && <MergeButton kind="prop" record={x} options={p.props} />} />)}
        </ul>
      </Section>

      <Section title={`Costumes (${p.costumes.length})`} description="Kept until the story gives a reason to change.">
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{p.costumes.map((k) => <CostumeCard key={k.id} p={p} k={k} />)}</ul>
      </Section>

      <Section title={`Locations (${p.locations.length})`} description="One record each, reused across scenes.">
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {p.locations.map((l) => <LocationCard key={l.id} l={l} actions={!demo && <MergeButton kind="location" record={l} options={p.locations} />} />)}
        </ul>
      </Section>

      <Section title="Scenes" description="Open a scene to see who holds what, what changed, and the production elements.">
        <div className="space-y-3">{p.scenes.map((s) => <SceneCard key={s.scene_id} p={p} s={s} />)}</div>
      </Section>
    </>
  );
}
