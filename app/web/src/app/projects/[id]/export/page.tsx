"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, FileJson, FileText, FolderArchive, Package, ShieldCheck } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { PageHeader, Pill, Spinner } from "@/components/domain/bits";
import { useWorkspace } from "@/components/domain/workspace";
import { continuityReport, download, sceneBreakdown, screenplayText } from "@/lib/downloads";
import { DEMO_ID, api } from "@/lib/api";
import { useAct } from "@/lib/hooks";
import { rank } from "@/lib/stages";

type Item = { icon: React.ComponentType<{ className?: string }>; file: string; text: string; ready: boolean; action?: () => void; note?: string };

export default function ExportPage() {
  const { id, project: p } = useWorkspace();
  const r = rank(p);
  const act = useAct(id);
  const live = id !== DEMO_ID && r >= 5;
  const status = useQuery({ queryKey: ["export-status", id, p.status, p.assets.length], queryFn: () => api.exportStatus(id), enabled: live });
  const missing = status.data?.missing ?? [];
  const build = (partial: boolean) => act.mutate({ run: () => api.buildExport(id, partial), ok: () => "Package built" });
  const has = {
    breakdown: p.scenes.length > 0,
    screenplay: p.adapted_scenes.length > 0,
    report: p.continuity_checked,
  };

  const items: Item[] = [
    { icon: FileText, file: "adapted_screenplay.txt", text: "The adapted screenplay, with English glosses for review.", ready: has.screenplay, action: () => download("adapted_screenplay.txt", screenplayText(p, true), "text/plain"), note: has.screenplay ? undefined : "Rewrite the screenplay first" },
    { icon: FileJson, file: "scene_breakdown.json", text: "Scenes, characters, places, props and costumes as structured records.", ready: has.breakdown, action: () => download("scene_breakdown.json", JSON.stringify(sceneBreakdown(p), null, 2)), note: has.breakdown ? undefined : "Normalize the extraction first" },
    { icon: ShieldCheck, file: "continuity_report.md", text: "Every contradiction found, the scenes it affects, and what you accepted and why.", ready: has.report, action: () => download("continuity_report.md", continuityReport(p), "text/markdown"), note: has.report ? undefined : "Run the continuity check first" },
    { icon: FolderArchive, file: "project.json", text: "The complete project: every record, decision, review note and trace.", ready: true, action: () => download(`project_${p.id}.json`, JSON.stringify(p, null, 2)) },
  ];

  return (
    <>
      <PageHeader eyebrow="Step 8" title="Export centre" description="Everything produced for this adaptation. The full package holds the PDFs, the structured breakdown and every image with the prompt that reproduces it." />
      <section className="mb-6 rounded-2xl border bg-card p-4 shadow-card sm:p-5">
        <div className="flex flex-wrap items-center gap-4">
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-accent text-primary"><Package className="size-5" aria-hidden /></span>
          <div className="min-w-0 flex-1">
            <p className="font-medium">Full package (ZIP)</p>
            <p className="text-sm text-muted-foreground">adapted_screenplay.pdf · continuity_report.pdf · scene_breakdown.json · character_bible/ · costume_bible/ · scene_keyframes/</p>
            {live && missing.length > 0 && <p className="mt-1 text-sm text-warning">Not complete: {missing.join("; ")}.</p>}
            {!live && <p className="mt-1 text-sm text-muted-foreground">{id === DEMO_ID ? "The demo is read-only; build a package from your own project." : "Available after the screenplay is rewritten."}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button disabled={!live || act.isPending || missing.length > 0} onClick={() => build(false)}>{act.isPending ? <Spinner /> : <Package aria-hidden />} Build package</Button>
            {live && missing.length > 0 && r >= 5 && <Button variant="outline" disabled={act.isPending} onClick={() => build(true)}>Build without the missing</Button>}
            {live && status.data?.zip_ready && <a href={api.exportUrl(id)} download className={buttonVariants({ variant: "outline" })}><Download aria-hidden /> Download ZIP</a>}
          </div>
        </div>
      </section>
      <ul className="grid gap-3">
        {items.map((it) => (
          <li key={it.file} className="flex flex-wrap items-center gap-4 rounded-2xl border bg-card p-4 shadow-card sm:p-5">
            <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-accent text-primary"><it.icon className="size-5" aria-hidden /></span>
            <div className="min-w-0 flex-1"><p className="font-mono text-sm font-medium">{it.file}</p><p className="text-sm text-muted-foreground">{it.text}</p></div>
            {it.ready ? <Pill tone="success">Ready</Pill> : <Pill tone="neutral">{it.note ?? "Not yet"}</Pill>}
            <Button variant={it.ready ? "default" : "outline"} disabled={!it.ready} onClick={it.action}><Download aria-hidden /> Download</Button>
          </li>
        ))}
      </ul>
      {r < 5 && <p className="mt-6 text-sm text-muted-foreground">More becomes available as the project moves through approval and the rewrite.</p>}
    </>
  );
}
