"use client";

import { ImageIcon, Lock, LockOpen, RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Chip, PageHeader, Pill, Section, Spinner } from "@/components/domain/bits";
import { RunButton } from "@/components/domain/run-button";
import { useWorkspace } from "@/components/domain/workspace";
import { api } from "@/lib/api";
import { useAct } from "@/lib/hooks";
import { displayName, nativeName, sceneNo } from "@/lib/format";
import { rank } from "@/lib/stages";
import type { Asset } from "@/lib/types";
import { cn } from "@/lib/utils";

const TONE = { generated: "success", stale: "warning", failed: "danger", pending: "neutral" } as const;
const LABEL = { generated: "Generated", stale: "Out of date", failed: "Failed", pending: "Waiting" } as const;

/** The real image when there is one; otherwise an honest empty frame that says why. Click for the full view and provenance. */
function AssetImage({ asset, ratio = "aspect-[3/4]", caption }: { asset?: Asset; ratio?: string; caption: string }) {
  const { id, project } = useWorkspace();
  const act = useAct(id);
  const [big, setBig] = useState(false);
  const busy = project.job?.state === "running" || act.isPending;
  const has = asset && asset.path && (asset.status === "generated" || asset.status === "stale");
  const url = asset ? api.assetUrl(id, asset.id, `${asset.spec_hash}-${asset.attempts}`) : "";
  const refs = asset ? asset.reference_asset_ids.map((r) => project.assets.find((a) => a.id === r)).filter((a): a is Asset => !!a) : [];
  return (
    <div className="space-y-2">
      <div className={cn("relative grid place-items-center overflow-hidden rounded-xl border bg-muted/40", ratio)}>
        {has ? (
          <button type="button" onClick={() => setBig(true)} className="size-full cursor-zoom-in" aria-label={`Open ${caption}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={url} alt={caption} className="size-full object-cover" loading="lazy" />
          </button>
        ) : (
          <div className="px-4 text-center text-xs text-muted-foreground"><ImageIcon className="mx-auto mb-2 size-8 text-foreground/20" aria-hidden />{asset?.status === "failed" ? "Generation failed" : "Not generated yet"}</div>
        )}
        {asset && <span className="pointer-events-none absolute left-2 top-2"><Pill tone={TONE[asset.status]} className="bg-card/95">{LABEL[asset.status]}</Pill></span>}
      </div>
      {asset?.error && <p className="text-xs text-danger">{asset.error}</p>}
      {asset?.problems?.length ? <p className="text-xs text-warning">Check: {asset.problems.join("; ")}</p> : null}
      {asset && (
        <div className="flex items-center justify-between gap-2">
          <Button size="sm" variant="ghost" className="-ml-2 text-muted-foreground" onClick={() => setBig(true)}>Details</Button>
          <Button size="sm" variant="outline" disabled={busy || id === "demo"} onClick={() => act.mutate({ run: () => api.regenerateAsset(id, asset.id), ok: () => "New image requested" })}>
            {busy ? <Spinner /> : <RefreshCw aria-hidden />} Redo
          </Button>
        </div>
      )}
      {asset && (
        <Dialog open={big} onOpenChange={setBig}>
          <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
            <DialogHeader>
              <DialogTitle>{caption}</DialogTitle>
              <DialogDescription>Everything needed to reproduce this image.</DialogDescription>
            </DialogHeader>
            <div className="grid gap-5 md:grid-cols-[1.3fr_1fr]">
              {has && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={url} alt={caption} className="w-full rounded-xl border" />
              )}
              <dl className="space-y-3 text-sm">
                <div><dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Record</dt><dd className="mt-1 flex flex-wrap gap-1"><Chip>{asset.entity_id}</Chip><Chip>{asset.id}</Chip></dd></div>
                <div><dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Made by</dt><dd className="mt-1">{asset.model || "not generated"}{asset.seconds ? ` · ${asset.seconds.toFixed(0)}s` : ""} · {asset.size} · attempt {asset.attempts}</dd></div>
                <div><dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Spec hash</dt><dd className="mt-1"><Chip>{asset.spec_hash}</Chip> <span className="text-xs text-muted-foreground">changes if any input changes</span></dd></div>
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Reference images ({refs.length})</dt>
                  <dd className="mt-1 flex flex-wrap gap-2">
                    {refs.length === 0 ? <span className="text-muted-foreground">None: generated from the text alone, so later images can be conditioned on it.</span> : refs.map((r) => (
                      <figure key={r.id} className="w-20">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={api.assetUrl(id, r.id, `${r.spec_hash}-${r.attempts}`)} alt={r.id} className="aspect-[3/4] w-full rounded-lg border object-cover" loading="lazy" />
                        <figcaption className="mt-0.5 break-all text-[10px] text-muted-foreground">{r.entity_id}</figcaption>
                      </figure>
                    ))}
                  </dd>
                </div>
                <div><dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Prompt</dt><dd className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg bg-paper p-3 text-xs leading-relaxed">{asset.prompt}</dd></div>
              </dl>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

export default function VisualsPage() {
  const { project: p } = useWorkspace();
  const open = rank(p) >= 4;
  const ent = p.plan?.entities;
  const asset = (aid: string) => p.assets.find((a) => a.id === aid);
  const made = p.assets.filter((a) => a.status === "generated").length;
  const todo = p.assets.length - made;
  const scenes = [...p.scenes].sort((a, b) => a.number - b.number);

  return (
    <>
      <PageHeader eyebrow="Step 6" title="Visual pack" description="A character bible, a costume bible and one keyframe per scene, all generated from the approved records so the same person and the same clothes look the same everywhere." />
      <div className={cn("mb-8 flex flex-wrap items-center gap-3 rounded-2xl border p-4 text-sm", open ? "border-info-line bg-info-soft text-info" : "bg-card text-muted-foreground shadow-card")}>
        {open ? <LockOpen className="size-5 shrink-0" aria-hidden /> : <Lock className="size-5 shrink-0" aria-hidden />}
        <p className="min-w-0 flex-1">{open
          ? <><strong>The approval gate is open.</strong> {p.assets.length ? `${made} of ${p.assets.length} images are ready${todo ? `; ${todo} still to make.` : "."}` : "Nothing has been generated yet."} Every image is built from the approved records; the first look of each character is their reference, and later images are conditioned on it. Changing a character marks only their images out of date.</>
          : <><strong>Locked until you approve.</strong> Images are only ever generated from approved characters, costumes and plan.</>}</p>
        {open && <RunButton stage="visuals" disabled={rank(p) < 5 || (p.assets.length > 0 && todo === 0)}><Sparkles aria-hidden /> {p.assets.length ? (todo ? `Generate the ${todo} missing` : "All generated") : "Generate the visual pack"}</RunButton>}
      </div>
      {open && rank(p) < 5 && <p className="-mt-5 mb-8 text-sm text-muted-foreground">Write the adapted screenplay first; the images use its approved look.</p>}

      <Section title="Character bible" description="One reference image per person, reused for every later image.">
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {p.characters.map((c) => {
            const cp = ent?.characters.find((x) => x.character_id === c.id);
            const costumes = p.costumes.filter((k) => k.character_id === c.id);
            return (
              <li key={c.id} className="overflow-hidden rounded-2xl border bg-card shadow-card">
                <div className="p-3"><AssetImage asset={asset(`ASSET_CHARREF_${c.id}`)} caption={`Reference image of ${displayName(c, p.plan)}`} /></div>
                <div className="space-y-2 px-5 pb-5">
                  <div className="flex items-baseline justify-between gap-2"><h3 className="font-heading text-xl">{displayName(c, p.plan)}</h3><Chip>{c.id}</Chip></div>
                  <p className="gurmukhi text-lg leading-snug text-primary">{nativeName(c, p.plan)}</p>
                  <p className="text-sm text-muted-foreground">{c.role_adapted || cp?.role_adapted || c.role}</p>
                  <p className="text-sm leading-relaxed">{c.physical_description || cp?.appearance}</p>
                  <p className="flex flex-wrap gap-1 pt-1">{costumes.map((k) => <Pill key={k.id} tone="info">{k.id.replace("COST_", "").replaceAll("_", " ").toLowerCase()}</Pill>)}</p>
                </div>
              </li>
            );
          })}
        </ul>
      </Section>

      <Section title="Costume bible" description="Each look is generated once, then reused in every scene where it appears.">
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {p.costumes.map((k) => (
            <li key={k.id} className="overflow-hidden rounded-2xl border bg-card shadow-card">
              <div className="p-3"><AssetImage asset={asset(`ASSET_COSTUME_${k.id}`) ?? asset(`ASSET_CHARREF_${k.character_id}`)} ratio="aspect-[3/4]" caption={`Costume ${k.id}`} /></div>
              <div className="space-y-1.5 px-4 pb-4 text-sm">
                <p className="font-medium leading-snug">{k.garments || "Not described"}</p>
                <p className="text-xs text-muted-foreground">{displayName(p.characters.find((c) => c.id === k.character_id), p.plan)}</p>
                {k.colours && <p className="text-muted-foreground">{k.colours}</p>}
                <p className="flex flex-wrap gap-1 pt-1">{k.scene_ids.map((s) => <Chip key={s}>{s}</Chip>)}</p>
              </div>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Scene keyframes" description="One frame per scene: place, time, light, blocking and the approved costumes.">
        <ul className="grid gap-4 md:grid-cols-2">
          {scenes.map((s) => {
            const loc = p.locations.find((l) => l.id === s.location_id);
            const sp = p.plan?.scenes[s.scene_id];
            return (
              <li key={s.scene_id} className="overflow-hidden rounded-2xl border bg-card shadow-card">
                <div className="p-3"><AssetImage asset={asset(`ASSET_KEYFRAME_${s.scene_id}`)} ratio="aspect-[3/2]" caption={`${sceneNo(s.scene_id)} keyframe`} /></div>
                <div className="space-y-1.5 px-5 pb-5">
                  <h3 className="font-heading text-lg">{sceneNo(s.scene_id)}: {loc?.adapted_name || loc?.name}</h3>
                  <p className="text-sm text-muted-foreground">{s.time}{sp ? `. ${sp.setting_notes.split(". ").slice(0, 2).join(". ")}` : ""}</p>
                  <p className="flex flex-wrap gap-1 pt-1">{s.characters.map((cid) => <Pill key={cid}>{displayName(p.characters.find((c) => c.id === cid), p.plan)}</Pill>)}</p>
                </div>
              </li>
            );
          })}
        </ul>
      </Section>
    </>
  );
}
