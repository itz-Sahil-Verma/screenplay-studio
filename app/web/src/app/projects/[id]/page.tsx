"use client";

import { ArrowRight, BadgeCheck, Eye, FileSearch, Flag, Layers, ScrollText, ShieldAlert, Sparkles } from "lucide-react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { Pill, Section, type Tone } from "@/components/domain/bits";
import { RunButton } from "@/components/domain/run-button";
import { useWorkspace } from "@/components/domain/workspace";
import { counts, nextAction, pendingReviews, progress, rank } from "@/lib/stages";
import { Progress } from "@/components/ui/progress";
import { plural } from "@/lib/format";

function LedgerRow({ icon: Icon, title, detail, tone, label, href }: { icon: React.ComponentType<{ className?: string }>; title: string; detail: string; tone: Tone; label: string; href: string }) {
  return (
    <li>
      <Link href={href} className="group flex items-center gap-4 rounded-xl px-3 py-3 transition-colors hover:bg-muted">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent text-primary"><Icon className="size-4.5" aria-hidden /></span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold">{title}</span>
          <span className="block text-sm text-muted-foreground">{detail}</span>
        </span>
        <Pill tone={tone}>{label}</Pill>
        <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
      </Link>
    </li>
  );
}

export default function Overview() {
  const { id, project: p, demo } = useWorkspace();
  const c = counts(p);
  const r = rank(p);
  const next = nextAction(p);
  const base = `/projects/${id}`;
  const pct = progress(p);
  const pending = pendingReviews(p);

  return (
    <>
      <section className="mb-6 overflow-hidden rounded-3xl border bg-card shadow-card">
        <div className="flex flex-col gap-6 border-l-4 border-primary p-6 sm:p-8 lg:flex-row lg:items-center lg:justify-between">
          <div className="max-w-2xl">
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-primary"><Sparkles className="size-3.5" aria-hidden /> {demo ? "Recorded run" : "Next step"}</p>
            <h2 className="text-2xl font-medium sm:text-3xl">{demo ? "A complete run, start to finish" : next.label}</h2>
            <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">
              {demo ? "Walk through the steps above. Every check, flag, decision and image is real output from this run." : next.description}
            </p>
            <div className="mt-5 max-w-md" aria-label={`Progress ${pct}%`}>
              <div className="mb-1.5 flex justify-between text-xs font-medium text-muted-foreground"><span>Pipeline progress</span><span className="tnum">{pct}%</span></div>
              <Progress value={pct} />
            </div>
          </div>
          <div className="shrink-0">
            {demo ? (
              <Link href={`${base}/trace`} className={buttonVariants({ size: "lg" }) + " h-11 px-5"}>Follow one character end to end <ArrowRight aria-hidden /></Link>
            ) : next.stage ? (
              <RunButton stage={next.stage} size="lg" className="h-11 px-5 text-[15px]">{next.label}</RunButton>
            ) : (
              <Link href={base + (next.path ?? "")} className={buttonVariants({ size: "lg" }) + " h-11 px-5"}>{next.label} <ArrowRight aria-hidden /></Link>
            )}
          </div>
        </div>
      </section>

      <ul className="mb-10 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {[
          { label: "Scenes", value: c.scenes, href: "/extract" },
          { label: "Characters", value: c.characters, href: "/extract" },
          { label: "Locations", value: p.locations.length, href: "/extract" },
          { label: "Props", value: p.props.length, href: "/extract" },
          { label: "Warnings", value: c.warnings + c.errors, href: "/continuity", tone: c.blocking ? "danger" : c.warnings + c.errors ? "warning" : "success" },
          { label: "To review", value: pending, href: "/plan", tone: pending ? "warning" : "success" },
        ].map((x) => (
          <li key={x.label}><Link href={base + x.href} className="block rounded-xl border bg-card p-4 shadow-card transition-colors hover:bg-muted/50">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{x.label}</p>
            <p className={"tnum mt-1 font-heading text-3xl " + (x.tone === "danger" ? "text-danger" : x.tone === "warning" ? "text-warning" : x.tone === "success" ? "text-success" : "")}>{r >= 1 || x.label === "Scenes" ? x.value : "–"}</p>
          </Link></li>
        ))}
      </ul>

      <Section title="What the system checked" description="Each row is a safeguard, and links to the evidence.">
        <ul className="divide-y rounded-2xl border bg-card p-2 shadow-card">
          <LedgerRow icon={FileSearch} title="Extraction" href={`${base}/extract`} tone={r >= 1 ? "success" : "neutral"} label={r >= 1 ? "Done" : "Not run"}
            detail={r >= 1 ? `${plural(p.source_scenes.length, "scene")} read. Characters or props not found in the text were rejected.` : "Each scene is read into structured records and every claim is checked against the source text."} />
          <LedgerRow icon={Layers} title="Identity" href={`${base}/extract`} tone={r >= 2 ? "success" : "neutral"} label={r >= 2 ? "Done" : "Pending"}
            detail={r >= 2 ? `${plural(c.characters, "character")} after merging aliases; ${plural(p.costumes.length, "costume")}; ${plural(p.props.length, "prop")}.` : "Aliases become one character; duplicates are merged into one record."} />
          <LedgerRow icon={ShieldAlert} title="Continuity" href={`${base}/continuity`} tone={c.blocking ? "danger" : p.continuity_checked ? "success" : "neutral"} label={c.blocking ? `${c.blocking} blocking` : p.continuity_checked ? "Clear" : "Pending"}
            detail={p.continuity_checked ? `${plural(p.warnings.length, "finding")}. Contradictions are caught before anything is generated.` : "Props, costumes and injuries are tracked across scenes."} />
          <LedgerRow icon={Flag} title="Cultural plan" href={`${base}/plan`} tone={c.flagged ? "warning" : p.plan ? "success" : "neutral"} label={c.flagged ? `${c.flagged} to review` : p.plan ? "Reviewed" : "Pending"}
            detail={p.plan ? `${plural(c.decisions, "decision")}; decisions resting on unverified cultural facts are flagged.` : "Explained decisions, grounded in a sourced culture pack."} />
          <LedgerRow icon={BadgeCheck} title="Human approval" href={`${base}/approve`} tone={c.approvals === 3 ? "success" : "warning"} label={`${c.approvals} of 3`}
            detail="Characters, costumes and plan are approved separately. Nothing is generated before all three." />
          <LedgerRow icon={ScrollText} title="Rewrite" href={`${base}/rewrite`} tone={p.adapted_scenes.length ? "success" : "neutral"} label={p.adapted_scenes.length ? "Written" : "Pending"}
            detail={p.adapted_scenes.length ? `${plural(c.lines, "line")}, each traced to its source line and the decisions behind it.` : "Every source line must be adapted, in order, in the chosen script."} />
        </ul>
      </Section>

      {(p.extraction_problems.length > 0 || p.normalization_log.length > 0) && (
        <Section title="Run notes" description="What the pipeline decided along the way.">
          <div className="space-y-3">
            {p.extraction_problems.length > 0 && (
              <details className="rounded-2xl border bg-card p-4 shadow-card open:pb-5" open>
                <summary className="flex cursor-pointer items-center gap-2 text-sm font-semibold"><Eye className="size-4 text-info" aria-hidden /> Input notes ({p.extraction_problems.length})</summary>
                <ul className="mt-3 list-disc space-y-1 pl-6 text-sm text-muted-foreground">{p.extraction_problems.map((m, i) => <li key={i}>{m}</li>)}</ul>
              </details>
            )}
            {p.normalization_log.length > 0 && (
              <details className="rounded-2xl border bg-card p-4 shadow-card">
                <summary className="flex cursor-pointer items-center gap-2 text-sm font-semibold"><Layers className="size-4 text-info" aria-hidden /> Identity decisions ({p.normalization_log.length})</summary>
                <ul className="mt-3 list-disc space-y-1 pl-6 text-sm text-muted-foreground">{p.normalization_log.map((m, i) => <li key={i}>{m}</li>)}</ul>
              </details>
            )}
          </div>
        </Section>
      )}
    </>
  );
}
