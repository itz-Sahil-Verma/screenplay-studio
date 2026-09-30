"use client";

import { ArrowRight, CloudOff, FolderOpen, PlayCircle, Plus } from "lucide-react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, Pill, StatusBadge } from "@/components/domain/bits";
import { useProjects, errorMessage } from "@/lib/hooks";
import { plural } from "@/lib/format";
import { api } from "@/lib/api";
import { STATUS_ORDER } from "@/lib/stages";
import { Progress } from "@/components/ui/progress";

export default function Dashboard() {
  const { data, error, isLoading } = useProjects();
  return (
    <div className="mx-auto max-w-7xl px-4 sm:px-6">
      <section className="py-10 sm:py-14">
        <p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-primary">Cultural adaptation studio</p>
        <h1 className="max-w-3xl text-4xl font-medium leading-[1.1] sm:text-6xl">Re-create a story inside a culture, not just a language.</h1>
        <p className="mt-5 max-w-2xl text-lg leading-relaxed text-muted-foreground">
          Upload a screenplay, choose an exact dialect and setting, and get an adapted screenplay where every choice is explained, checked and approved by you.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/new" className={buttonVariants({ size: "lg" }) + " h-11 px-5 text-[15px]"}><Plus aria-hidden /> New adaptation</Link>
          <Link href="/projects/demo" className={buttonVariants({ size: "lg", variant: "outline" }) + " h-11 bg-card px-5 text-[15px]"}><PlayCircle aria-hidden /> Explore a recorded run</Link>
        </div>
      </section>

      <section aria-labelledby="projects" className="pb-20">
        <h2 id="projects" className="mb-4 text-xl font-medium">Your adaptations</h2>
        {isLoading && <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40 rounded-2xl" />)}</div>}
        {error && (
          <EmptyState icon={CloudOff} title="The API is not reachable" description={`${errorMessage(error)}. The recorded demo still works without it.`}
            action={<Link href="/projects/demo" className={buttonVariants({ variant: "outline" })}>Open the recorded demo</Link>} />
        )}
        {data && data.length === 0 && (
          <EmptyState icon={FolderOpen} title="No adaptations yet" description="Start one from a pasted screenplay or an uploaded file."
            action={<Link href="/new" className={buttonVariants()}><Plus aria-hidden /> New adaptation</Link>} />
        )}
        {data && data.length > 0 && (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.map((p) => (
              <li key={p.id}>
                <Link href={`/projects/${p.id}`} className="card-lift group block overflow-hidden rounded-2xl border bg-card">
                  {(p.status === "generated" || p.status === "exported") && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={api.assetUrl(p.id, "ASSET_KEYFRAME_SC01")} alt="First scene keyframe" className="aspect-[3/1] w-full object-cover" loading="lazy" />
                  )}
                  <div className="p-5">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="truncate font-heading text-lg">{p.source_filename || "Untitled"}</h3>
                      <StatusBadge status={p.status} />
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">{p.culture || "Unknown culture"}{p.region ? ` · ${p.region}` : ""}</p>
                    <div className="mt-4"><Progress value={Math.round((Math.max(0, STATUS_ORDER.indexOf(p.status as (typeof STATUS_ORDER)[number])) / 7) * 100)} /></div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      <Pill>{plural(p.scenes, "scene")}</Pill>
                      <Pill>{plural(p.characters, "character")}</Pill>
                      {p.flagged_decisions > 0 && <Pill tone="warning">{p.flagged_decisions} to review</Pill>}
                    </div>
                    <span className="mt-4 flex items-center gap-1 text-sm font-medium text-primary">Open <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden /></span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
