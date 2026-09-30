import { AlertOctagon, ArrowRight, BookOpenCheck, CheckCircle2, CircleDashed, Flag, Info, Lightbulb, Loader2, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { STATUS_LABEL } from "@/lib/format";
import { rank, STATUS_ORDER } from "@/lib/stages";

export type Tone = "success" | "warning" | "danger" | "info" | "primary" | "neutral";

const TONE: Record<Tone, string> = {
  success: "bg-success-soft text-success border-success-line",
  warning: "bg-warning-soft text-warning border-warning-line",
  danger: "bg-danger-soft text-danger border-danger-line",
  info: "bg-info-soft text-info border-info-line",
  primary: "bg-accent text-accent-foreground border-primary/20",
  neutral: "bg-muted text-muted-foreground border-border",
};

/** A small labelled pill. Status is always icon + word, never colour alone. */
export function Pill({ tone = "neutral", icon: Icon, children, className, title }: {
  tone?: Tone; icon?: React.ComponentType<{ className?: string }>; children: React.ReactNode; className?: string; title?: string;
}) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium leading-5 whitespace-nowrap", TONE[tone], className)}>
      {Icon && <Icon className="size-3.5" aria-hidden />}
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const r = STATUS_ORDER.indexOf(status as (typeof STATUS_ORDER)[number]);
  const tone: Tone = r >= 4 ? "success" : r === 3 ? "warning" : r >= 1 ? "info" : "neutral";
  const icon = r >= 4 ? CheckCircle2 : r === 3 ? Flag : CircleDashed;
  return <Pill tone={tone} icon={icon}>{STATUS_LABEL[status] ?? status}</Pill>;
}

export const FlagBadge = ({ reason }: { reason?: string }) => (
  <Pill tone="warning" icon={Flag} title={reason}>Needs review</Pill>
);

export const BasisBadge = ({ basis }: { basis: string }) =>
  basis === "pack" ? <Pill tone="info" icon={BookOpenCheck} title="Backed by facts in the culture pack">Pack-backed</Pill>
    : <Pill tone="neutral" icon={Lightbulb} title="A creative choice by the model, not backed by a pack fact">Model judgment</Pill>;

export function SeverityBadge({ severity, acknowledged }: { severity: string; acknowledged?: boolean }) {
  if (acknowledged) return <Pill tone="success" icon={CheckCircle2}>Acknowledged</Pill>;
  if (severity === "error") return <Pill tone="danger" icon={AlertOctagon}>Blocking</Pill>;
  if (severity === "warning") return <Pill tone="warning" icon={TriangleAlert}>Warning</Pill>;
  return <Pill tone="info" icon={Info}>Note</Pill>;
}

export const Spinner = ({ className }: { className?: string }) => <Loader2 className={cn("size-4 animate-spin", className)} aria-hidden />;

/** Monospace chip for ids like CHAR_RAVI, DEC012, F028. */
export const Chip = ({ children, className }: { children: React.ReactNode; className?: string }) => (
  <span className={cn("inline-flex items-center rounded-md border bg-paper px-1.5 py-0.5 font-mono text-[11px] leading-4 text-muted-foreground", className)}>{children}</span>
);

/** Scene 2 → 3 → 4, for the stretch of the story a finding affects. */
export function SceneSpan({ ids }: { ids: string[] }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
      {ids.map((id, i) => (
        <span key={id} className="inline-flex items-center gap-1">
          {i > 0 && <ArrowRight className="size-3" aria-hidden />}
          <span className="rounded-md bg-muted px-1.5 py-0.5 font-medium text-foreground/80">Scene {Number(id.replace(/\D/g, ""))}</span>
        </span>
      ))}
    </span>
  );
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="max-w-2xl">
        {eyebrow && <p className="mb-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-primary">{eyebrow}</p>}
        <h1 className="text-3xl font-medium leading-tight sm:text-4xl">{title}</h1>
        {description && <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, description, action }: { icon: React.ComponentType<{ className?: string }>; title: string; description?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed bg-card/60 px-6 py-14 text-center">
      <span className="mb-4 grid size-12 place-items-center rounded-full bg-accent text-primary"><Icon className="size-6" /></span>
      <h3 className="font-heading text-xl">{title}</h3>
      {description && <p className="mt-1.5 max-w-md text-sm leading-relaxed text-muted-foreground">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, tone = "neutral" }: { label: string; value: React.ReactNode; hint?: string; tone?: Tone }) {
  const color = tone === "neutral" ? "text-foreground" : tone === "primary" ? "text-primary" : { success: "text-success", warning: "text-warning", danger: "text-danger", info: "text-info" }[tone];
  return (
    <div className="rounded-xl border bg-card p-4 shadow-card">
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={cn("tnum mt-1 font-heading text-3xl", color)}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export const Section = ({ title, description, children, action }: { title: string; description?: string; children: React.ReactNode; action?: React.ReactNode }) => (
  <section className="mb-10">
    <div className="mb-4 flex items-end justify-between gap-4">
      <div>
        <h2 className="text-xl font-medium">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
    {children}
  </section>
);

export { rank };
