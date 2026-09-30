"use client";

import { CheckCheck, Flag, RefreshCw, Sparkles, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Chip, EmptyState, PageHeader, Pill, Spinner } from "@/components/domain/bits";
import { BlockingBanner } from "@/components/domain/blocking-banner";
import { CompactDecision, DecisionCard } from "@/components/domain/decision-card";
import { EditPlanButton } from "@/components/domain/edit-plan";
import { RunButton } from "@/components/domain/run-button";
import { useWorkspace } from "@/components/domain/workspace";
import { api } from "@/lib/api";
import { DIMENSION_LABEL, displayName, sceneNo } from "@/lib/format";
import { useAct } from "@/lib/hooks";
import { counts, rank } from "@/lib/stages";
import { cn } from "@/lib/utils";

type Filter = "all" | "unreviewed" | "story";
const select = "h-9 rounded-lg border border-input bg-card px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  if (!children || (Array.isArray(children) && children.length === 0)) return null;
  return <div><dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</dt><dd className="mt-0.5 text-sm leading-relaxed">{children}</dd></div>;
}

export default function PlanPage() {
  const { id, project: p, demo } = useWorkspace();
  const act = useAct(id);
  const [filter, setFilter] = useState<Filter>("all");
  const [dim, setDim] = useState("all");
  const [confirm, setConfirm] = useState(false);
  const c = counts(p);

  if (!p.plan || !p.plan.entities || rank(p) < 3)
    return (
      <>
        <PageHeader eyebrow="Step 3" title="Cultural adaptation plan" description="Explained decisions about names, speech, clothing, places and gestures, grounded in a sourced culture pack." />
        <EmptyState icon={Sparkles} title="No plan yet" description={rank(p) < 2 ? "Extract and normalize the screenplay first." : "The model will propose the adaptation; you review every decision."}
          action={!demo && rank(p) >= 2 && <RunButton stage="plan" size="lg">Generate the adaptation plan</RunButton>} />
      </>
    );

  const ent = p.plan.entities;
  const nameOf = (eid: string | null) => {
    if (!eid) return undefined;
    if (eid.startsWith("CHAR_")) return displayName(p.characters.find((x) => x.id === eid), p.plan) || eid;
    if (eid.startsWith("COST_")) return p.costumes.find((x) => x.id === eid)?.garments || eid;
    if (eid.startsWith("LOC_")) return p.locations.find((x) => x.id === eid)?.adapted_name || p.locations.find((x) => x.id === eid)?.name || eid;
    if (eid.startsWith("PROP_")) return p.props.find((x) => x.id === eid)?.name || eid;
    if (eid.startsWith("SC")) return sceneNo(eid);
    return eid;
  };

  const shown = p.decisions.filter((d) =>
    (dim === "all" || d.dimension === dim) &&
    (filter === "all" || (filter === "unreviewed" && d.status === "proposed") || (filter === "story" && d.dimension === "story_world")));
  const toAccept = shown.filter((d) => d.status === "proposed");  // only what is in view, and only what nobody has decided yet
  const flaggedInView = toAccept.filter((d) => d.uncertain).length;
  const stale = p.plan.stale_scenes;

  const acceptAll = () =>
    act.mutate({ run: async () => { for (const d of toAccept) await api.reviewDecision(id, d.id, "accepted"); }, ok: () => `Accepted ${toAccept.length} decision${toAccept.length > 1 ? "s" : ""}` },
      { onSuccess: () => setConfirm(false) });

  const FILTERS: [Filter, string, number][] = [["all", "All", c.decisions], ["unreviewed", "To review", c.unreviewed], ["story", "Story changes", p.decisions.filter((d) => d.dimension === "story_world").length]];

  return (
    <>
      <PageHeader eyebrow="Step 3" title="Cultural adaptation plan"
        description="Every choice the model proposes, with its reason and what it rests on. Pack-backed means it cites facts from the culture pack. Flagged marks a decision to read with extra care (it relies on an unverified fact, changes the story, or the model was unsure); it stays flagged after you accept it."
        actions={!demo && <Button variant="outline" disabled={act.isPending || p.job?.state === "running"} onClick={() => act.mutate({ run: () => api.replanEntities(id), ok: () => "Re-planning started" })}><RefreshCw aria-hidden /> Regenerate the cast plan</Button>} />

      <BlockingBanner id={id} project={p} />

      <div className="mb-6 rounded-2xl border bg-card p-5 shadow-card">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">The world, fixed for every scene</p>
        <p className="mt-1 font-heading text-xl leading-snug">{ent.season_and_period}</p>
      </div>

      {p.plan.problems.length > 0 && (
        <div role="alert" className="mb-6 rounded-2xl border border-danger-line bg-danger-soft p-4 text-sm text-danger">
          <p className="mb-1.5 flex items-center gap-2 font-semibold"><TriangleAlert className="size-4" aria-hidden /> {p.plan.problems.length} problem(s) to fix before approval</p>
          <ul className="list-disc space-y-0.5 pl-6">{p.plan.problems.map((m, i) => <li key={i}>{m}</li>)}</ul>
        </div>
      )}
      {stale.length > 0 && (
        <div className="mb-6 rounded-2xl border border-warning-line bg-warning-soft p-4 text-sm text-warning">
          <p className="mb-2 font-semibold">An edit changed the inputs of these scenes: re-plan them, or keep their current plan.</p>
          <ul className="space-y-2">
            {stale.map((s) => (
              <li key={s} className="flex flex-wrap items-center gap-2"><span className="font-medium">{sceneNo(s)}</span>
                {!demo && <><Button size="sm" variant="outline" className="bg-card" onClick={() => act.mutate({ run: () => api.replanScene(id, s), ok: () => `Re-planning ${sceneNo(s)}` })}><RefreshCw aria-hidden /> Re-plan</Button>
                  <Button size="sm" variant="ghost" onClick={() => act.mutate({ run: () => api.keepScene(id, s), ok: () => `Kept the plan for ${sceneNo(s)}` })}>Keep as it is</Button></>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Tabs defaultValue="decisions">
        <TabsList className="mb-5 flex-wrap">
          <TabsTrigger value="decisions">Decisions</TabsTrigger>
          <TabsTrigger value="cast">Cast</TabsTrigger>
          <TabsTrigger value="costumes">Costumes</TabsTrigger>
        </TabsList>

        <TabsContent value="decisions">
          <div className="mb-5 flex flex-wrap items-center gap-2">
            {FILTERS.map(([k, label, n]) => (
              <button key={k} onClick={() => setFilter(k)} aria-pressed={filter === k}
                className={cn("rounded-full border px-3 py-1.5 text-sm font-medium transition-colors", filter === k ? "border-primary bg-primary text-primary-foreground" : "bg-card hover:bg-muted")}>{label} <span className="tnum opacity-70">{n}</span></button>
            ))}
            <label className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">Topic
              <select className={select} value={dim} onChange={(e) => setDim(e.target.value)}>
                <option value="all">All topics</option>{Object.entries(DIMENSION_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            {!demo && toAccept.length > 0 && (
              <Button variant="outline" disabled={act.isPending} onClick={() => (flaggedInView > 0 ? setConfirm(true) : acceptAll())}>
                {act.isPending ? <Spinner /> : <CheckCheck aria-hidden />} Accept all{dim !== "all" ? ` ${DIMENSION_LABEL[dim] ?? dim}` : ""} ({toAccept.length})
              </Button>
            )}
          </div>
          {shown.length === 0 ? <EmptyState icon={Flag} title="Nothing matches this filter" /> : (
            <ul className="space-y-3">{shown.map((d) => d.uncertain || d.status === "proposed" ? <DecisionCard key={d.id} d={d} entityName={nameOf(d.entity_id)} /> : <CompactDecision key={d.id} d={d} entityName={nameOf(d.entity_id)} />)}</ul>
          )}
        </TabsContent>

        <TabsContent value="cast">
          <ul className="grid gap-4 lg:grid-cols-2">
            {ent.characters.map((cp) => {
              const src = p.characters.find((x) => x.id === cp.character_id);
              return (
                <li key={cp.character_id} className="rounded-2xl border bg-card p-5 shadow-card">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs text-muted-foreground">Source: {src?.name}{src?.age ? `, ${src.age}` : ""}</p>
                      <h3 className="font-heading text-2xl leading-tight">{cp.name_roman}</h3>
                      <p className="gurmukhi text-xl text-primary">{cp.name_native}</p>
                    </div>
                    <EditPlanButton kind="character" entityId={cp.character_id} title={cp.name_roman} values={{ name_roman: cp.name_roman, name_native: cp.name_native, role_adapted: cp.role_adapted, appearance: cp.appearance, grooming: cp.grooming, speech_register: cp.speech_register }}
                      fields={[{ key: "name_roman", label: "Name (Latin letters)" }, { key: "name_native", label: "Name (in the output script)", native: true }, { key: "role_adapted", label: "Role", long: true }, { key: "appearance", label: "Appearance", long: true }, { key: "grooming", label: "Grooming", long: true }, { key: "speech_register", label: "How they speak", long: true }]} />
                  </div>
                  <dl className="mt-3 space-y-3">
                    <Field label="Role">{cp.role_adapted}</Field><Field label="Appearance">{cp.appearance}</Field><Field label="Grooming">{cp.grooming}</Field><Field label="Speech">{cp.speech_register}</Field>
                    <Field label="Addressed as"><span className="flex flex-wrap gap-1">{cp.address_terms.map((a) => <Pill key={a}>{a}</Pill>)}</span></Field>
                  </dl>
                </li>
              );
            })}
          </ul>
        </TabsContent>

        <TabsContent value="costumes">
          <ul className="grid gap-4 lg:grid-cols-2">
            {ent.costumes.map((k) => {
              const src = p.costumes.find((x) => x.id === k.costume_id);
              const who = p.characters.find((x) => x.id === src?.character_id);
              return (
                <li key={k.costume_id} className="rounded-2xl border bg-card p-5 shadow-card">
                  <div className="flex items-start justify-between gap-3">
                    <div><p className="text-xs text-muted-foreground">{displayName(who, p.plan)} · {src?.scene_ids.map((s) => sceneNo(s).replace("Scene ", "S")).join(", ")}</p>
                      <h3 className="font-heading text-xl leading-snug">{k.garments}</h3>
                      {src?.source_garments && <p className="text-xs text-muted-foreground">Source said: {src.source_garments}</p>}</div>
                    <EditPlanButton kind="costume" entityId={k.costume_id} title={k.garments} values={{ garments: k.garments, fabrics: k.fabrics, colours: k.colours, footwear: k.footwear, jewellery: k.jewellery, headwear: k.headwear, grooming: k.grooming, change_reason: k.change_reason }}
                      fields={["garments", "fabrics", "colours", "footwear", "jewellery", "headwear", "grooming", "change_reason"].map((key) => ({ key, label: key.replace("_", " ").replace(/^./, (m) => m.toUpperCase()), long: true }))} />
                  </div>
                  <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                    <Field label="Fabrics">{k.fabrics}</Field><Field label="Colours">{k.colours}</Field><Field label="Footwear">{k.footwear}</Field>
                    <Field label="Jewellery">{k.jewellery}</Field><Field label="Headwear">{k.headwear}</Field><Field label="Grooming">{k.grooming}</Field>
                  </dl>
                  {k.change_reason && <p className="mt-3 rounded-lg bg-info-soft p-3 text-sm text-info"><strong>Reason for the change:</strong> {k.change_reason}</p>}
                </li>
              );
            })}
          </ul>
        </TabsContent>
      </Tabs>
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Accept {toAccept.length} decisions?</DialogTitle>
            <DialogDescription>
              {flaggedInView} of them {flaggedInView === 1 ? "is" : "are"} flagged: they rely on an unverified culture fact, change the story, or the model was unsure. Accepting records that you have read them. You can still reopen or edit any decision later.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(false)}>Cancel</Button>
            <Button onClick={acceptAll} disabled={act.isPending}>{act.isPending && <Spinner />} Accept all {toAccept.length}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <p className="mt-6 text-xs text-muted-foreground">Plan by <Chip>{p.plan.model || "model"}</Chip></p>
    </>
  );
}
