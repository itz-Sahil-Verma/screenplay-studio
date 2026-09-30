"use client";

import { FlaskConical, GitBranch, Globe2, MapPin, SearchX, TreePine, Building2, Type } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { buttonVariants } from "@/components/ui/button";
import { usePathname } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, Pill, StatusBadge } from "@/components/domain/bits";
import { JobBanner } from "@/components/domain/job-banner";
import { StepNav } from "@/components/domain/step-nav";
import { Stepper } from "@/components/domain/stepper";
import { prettyPack, WorkspaceProvider } from "@/components/domain/workspace";
import { ApiError, DEMO_ID } from "@/lib/api";
import { useProject } from "@/lib/hooks";

const SCRIPT: Record<string, string> = { gurmukhi: "Gurmukhi", devanagari: "Devanagari", latin: "Roman", shahmukhi: "Shahmukhi" };

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const path = usePathname();
  const { data: project, error, isLoading } = useProject(id);

  if (isLoading)
    return (
      <div className="mx-auto max-w-7xl space-y-4 px-4 py-8 sm:px-6">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-20 w-full rounded-2xl" />
        <Skeleton className="h-96 w-full rounded-2xl" />
      </div>
    );

  if (error || !project)
    return (
      <div className="mx-auto max-w-2xl px-4 py-16">
        <EmptyState
          icon={SearchX}
          title={error instanceof ApiError && error.status === 404 ? "Project not found" : "Could not load this project"}
          description={error instanceof Error ? error.message : undefined}
          action={<Link href="/" className={buttonVariants()}>Back to projects</Link>}
        />
      </div>
    );

  const sel = project.selection;
  return (
    <WorkspaceProvider id={id} project={project}>
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        {id === DEMO_ID && (
          <div className="mb-5 flex items-start gap-3 rounded-2xl border border-info-line bg-info-soft p-4 text-sm text-info">
            <FlaskConical className="mt-0.5 size-5 shrink-0" aria-hidden />
            <p>
              <strong>Recorded demo, read-only.</strong> This is a real run on the sample screenplay (GPT-5 and gpt-image-2 through Azure). A person reviewed it in the app: 36 decisions accepted, 2 rejected, 2 continuity findings accepted with a reason. No native speaker has reviewed the Gurmukhi or the culture facts.
              Everything here is browsable; to change anything, <Link href="/new" className="font-semibold underline underline-offset-2">start a new adaptation</Link>.
            </p>
          </div>
        )}
        <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="font-heading text-2xl font-medium"><Link href={`/projects/${id}`} className="rounded-md underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2" title="Back to the project overview">{project.source_filename || "Untitled screenplay"}</Link></h1>
          <StatusBadge status={project.status} />
          {sel && (
            <div className="flex flex-wrap items-center gap-1.5">
              <Pill tone="primary" icon={Globe2}>{prettyPack(sel.pack_id)}</Pill>
              <Pill icon={MapPin}>{sel.region}</Pill>
              <Pill icon={sel.setting === "rural" ? TreePine : Building2}>{sel.setting === "rural" ? "Rural" : "Urban"}</Pill>
              <Pill icon={Type}>{SCRIPT[sel.output_script] ?? sel.output_script}</Pill>
            </div>
          )}
          <Link href={`/projects/${id}/trace`} aria-current={path.endsWith("/trace") ? "page" : undefined} className={buttonVariants({ variant: path.endsWith("/trace") ? "default" : "outline", size: "sm" }) + " ml-auto"}><GitBranch aria-hidden /> Trace</Link>
        </div>
        <Stepper id={id} project={project} />
        <JobBanner job={project.job} />
        {children}
        <StepNav id={id} project={project} />
      </div>
    </WorkspaceProvider>
  );
}
