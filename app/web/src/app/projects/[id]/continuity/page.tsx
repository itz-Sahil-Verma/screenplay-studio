"use client";

import { Download, RefreshCw, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PropGrid, CostumeGrid } from "@/components/domain/continuity-grid";
import { EmptyState, PageHeader, Section, Spinner, Stat } from "@/components/domain/bits";
import { WarningCard } from "@/components/domain/warning-card";
import { RunButton } from "@/components/domain/run-button";
import { useWorkspace } from "@/components/domain/workspace";
import { api } from "@/lib/api";
import { continuityReport, download } from "@/lib/downloads";
import { useAct } from "@/lib/hooks";
import { counts, rank, warningNumber } from "@/lib/stages";

export default function ContinuityPage() {
  const { id, project: p, demo } = useWorkspace();
  const act = useAct(id);
  const c = counts(p);

  if (!p.continuity_checked || rank(p) < 2)
    return (
      <>
        <PageHeader eyebrow="Step 2" title="Continuity report" description="Contradictions found by code, before anything is generated." />
        <EmptyState icon={ShieldCheck} title="Not checked yet" description="Normalize the extraction first; the check runs on the merged records."
          action={!demo && <RunButton stage={rank(p) === 0 ? "extract" : "normalize"} size="lg">{rank(p) === 0 ? "Extract scenes" : "Normalize and check continuity"}</RunButton>} />
      </>
    );

  return (
    <>
      <PageHeader eyebrow="Step 2" title="Continuity report"
        description="Found by plain code, not by the model, so the same records always give the same findings. Each lists every scene it touches. Blocking findings must be fixed or accepted with a reason before you can approve."
        actions={<>
          <Button variant="outline" onClick={() => download("continuity_report.md", continuityReport(p), "text/markdown")}><Download aria-hidden /> Download report</Button>
          {!demo && <Button variant="outline" disabled={act.isPending} onClick={() => act.mutate({ run: () => api.recheck(id), ok: () => "Re-checked" })}>{act.isPending ? <Spinner /> : <RefreshCw aria-hidden />} Re-run check</Button>}
        </>} />

      <div className="mb-8 grid grid-cols-3 gap-3">
        <Stat label="Blocking" value={c.blocking} tone={c.blocking ? "danger" : "success"} hint={c.errors ? `${c.errors} error finding(s)` : "nothing blocks approval"} />
        <Stat label="Warnings" value={c.warnings} tone={c.warnings ? "warning" : "neutral"} hint="need a human look" />
        <Stat label="Notes" value={c.infos} tone="info" hint="things the visuals must respect" />
      </div>

      <Section title="Who holds what" description="Each prop, scene by scene. Tinted cells are part of a finding below.">
        <PropGrid p={p} />
      </Section>
      <Section title="What each character wears" description="A change of clothes needs a story reason; tinted cells have none yet.">
        <CostumeGrid p={p} />
      </Section>

      <Section title={`Findings (${p.warnings.length})`} description="Most serious first.">
        {p.warnings.length === 0 ? <EmptyState icon={ShieldCheck} title="No findings" description="The records are consistent." /> : (
          <ul className="space-y-3">{p.warnings.map((w) => <WarningCard key={w.id} w={w} n={warningNumber(p, w.id)} />)}</ul>
        )}
      </Section>
    </>
  );
}
