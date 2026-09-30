"use client";

import { Download, Eye, Languages, RefreshCw, ScrollText, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { EmptyState, PageHeader, Pill, Spinner } from "@/components/domain/bits";
import { DecisionCard } from "@/components/domain/decision-card";
import { AdaptedScreenplay, SourceScreenplay, TraceDialog } from "@/components/domain/scene-split";
import { RunButton } from "@/components/domain/run-button";
import { useWorkspace } from "@/components/domain/workspace";
import { api } from "@/lib/api";
import { sceneNo } from "@/lib/format";
import { useAct } from "@/lib/hooks";
import { rank } from "@/lib/stages";
import type { AdaptedLine } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function RewritePage() {
  const { id, project: p, demo } = useWorkspace();
  const act = useAct(id);
  const [gloss, setGloss] = useState(true);
  const [active, setActive] = useState("SC01");
  const [line, setLine] = useState<AdaptedLine | null>(null);
  const r = rank(p);

  if (r < 4)
    return (
      <>
        <PageHeader eyebrow="Step 5" title="Source and adapted, side by side" description="The screenplay rewritten in the chosen language and script, every line traced to its source." />
        <EmptyState icon={ScrollText} title="Approve the plan first" description="The rewrite only uses approved decisions and records." action={<Link href={`/projects/${id}/approve`} className={buttonVariants()}>Go to approvals</Link>} />
      </>
    );
  if (p.adapted_scenes.length === 0 && Object.keys(p.rewrite_failed).length === 0)
    return (
      <>
        <PageHeader eyebrow="Step 5" title="Source and adapted, side by side" description="The screenplay rewritten in the chosen language and script, every line traced to its source." />
        <EmptyState icon={ScrollText} title="Ready to rewrite" description="One scene at a time. Every source dialogue line must be adapted, in order, in the chosen script, or the scene is retried."
          action={!demo && <RunButton stage="rewrite" size="lg">Rewrite the screenplay</RunButton>} />
      </>
    );

  const scenes = [...p.scenes].sort((a, b) => a.number - b.number);
  const scene = scenes.find((s) => s.scene_id === active) ?? scenes[0];
  const adapted = p.adapted_scenes.find((a) => a.source_scene_id === scene.scene_id);
  const failed = p.rewrite_failed[scene.scene_id];
  const why = p.decisions.filter((d) => d.status !== "rejected" && d.source_scene_ids.includes(scene.scene_id));

  return (
    <>
      <PageHeader eyebrow="Step 5" title="Source and adapted, side by side"
        description="Click any adapted line to see the source line, the story events and the decisions behind it. A flag marks a line the model was unsure of."
        actions={<>
          <label className="flex cursor-pointer items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm font-medium">
            <input type="checkbox" checked={gloss} onChange={(e) => setGloss(e.target.checked)} className="size-4 accent-[var(--primary)]" /> <Languages className="size-4 text-primary" aria-hidden /> English gloss
          </label>
          {!demo && <a href={api.screenplayUrl(id, gloss)} className={buttonVariants({ variant: "outline" })}><Download aria-hidden /> Text</a>}
        </>} />

      <div role="tablist" aria-label="Scenes" className="mb-4 flex flex-wrap gap-2">
        {scenes.map((s) => {
          const a = p.adapted_scenes.find((x) => x.source_scene_id === s.scene_id);
          const issue = !a || a.problems.length > 0;
          return (
            <button key={s.scene_id} role="tab" aria-selected={s.scene_id === scene.scene_id} onClick={() => setActive(s.scene_id)}
              className={cn("flex items-center gap-2 rounded-xl border px-4 py-2 text-sm font-medium transition-colors", s.scene_id === scene.scene_id ? "border-primary bg-primary text-primary-foreground shadow-card" : "bg-card hover:bg-muted")}>
              {sceneNo(s.scene_id)} {issue && <TriangleAlert className="size-3.5" aria-label="Has an issue" />}
            </button>
          );
        })}
      </div>

      {failed && <p role="alert" className="mb-4 rounded-xl border border-danger-line bg-danger-soft p-3.5 text-sm text-danger"><strong>This scene failed:</strong> {failed}</p>}
      {adapted && adapted.problems.length > 0 && (
        <div role="alert" className="mb-4 rounded-xl border border-warning-line bg-warning-soft p-3.5 text-sm text-warning">
          <p className="mb-1 font-semibold">The automatic checks found {adapted.problems.length} unresolved problem(s) in this scene:</p>
          <ul className="list-disc space-y-0.5 pl-5">{adapted.problems.map((m, i) => <li key={i}>{m}</li>)}</ul>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section aria-label="Source" className="rounded-2xl border bg-paper shadow-card">
          <header className="flex items-center gap-2 border-b px-5 py-3"><Eye className="size-4 text-muted-foreground" aria-hidden /><h2 className="font-sans text-sm font-semibold">Source</h2><Pill>{scene.int_ext}</Pill></header>
          <div className="max-h-[70vh] overflow-y-auto p-6"><SourceScreenplay text={scene.source_text} /></div>
        </section>
        <section aria-label="Adapted" className="rounded-2xl border bg-adapted shadow-card">
          <header className="flex items-center gap-2 border-b px-5 py-3"><Languages className="size-4 text-primary" aria-hidden /><h2 className="font-sans text-sm font-semibold">Adapted</h2>
            {adapted && <Pill tone="primary">{adapted.lines.length} lines</Pill>}
            {!demo && <Button size="sm" variant="ghost" className="ml-auto" disabled={act.isPending} onClick={() => act.mutate({ run: () => api.rewriteScene(id, scene.scene_id), ok: () => `Regenerating ${sceneNo(scene.scene_id)}` })}>{act.isPending ? <Spinner /> : <RefreshCw aria-hidden />} Regenerate</Button>}</header>
          <div className="max-h-[70vh] overflow-y-auto p-6">
            {adapted ? <AdaptedScreenplay p={p} a={adapted} gloss={gloss} onPick={setLine} /> : <p className="text-sm text-muted-foreground">This scene has not been rewritten yet.</p>}
          </div>
        </section>
      </div>

      {why.length > 0 && (
        <details className="mt-6 rounded-2xl border bg-card p-5 shadow-card">
          <summary className="cursor-pointer text-lg font-medium font-heading">Why it changed: {why.length} decisions for {sceneNo(scene.scene_id)}</summary>
          <ul className="mt-4 space-y-4">{why.map((d) => <DecisionCard key={d.id} d={d} />)}</ul>
        </details>
      )}
      <TraceDialog p={p} scene={scene} line={line} onClose={() => setLine(null)} />
    </>
  );
}
