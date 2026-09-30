"use client";

import { AlertCircle, ClipboardPaste, FileText, Loader2, Sparkles, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Chip, PageHeader } from "@/components/domain/bits";
import { api } from "@/lib/api";
import { errorMessage, usePacks } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const select = "h-10 w-full rounded-lg border border-input bg-card px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40";

function Field({ label, hint, children, htmlFor }: { label: string; hint?: string; children: React.ReactNode; htmlFor: string }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor} className="text-sm font-medium">{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export default function NewAdaptation() {
  const router = useRouter();
  const { data: packs, error: packsError } = usePacks();
  const [mode, setMode] = useState<"paste" | "upload">("paste");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  // Choices the user has made. Anything left null falls back to the pack's own default, so no effect is needed.
  const [packSel, setPackSel] = useState<string | null>(null);
  const [regionSel, setRegionSel] = useState<string | null>(null);
  const [settingSel, setSettingSel] = useState<string | null>(null);
  const [scriptSel, setScriptSel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const pack = packs?.find((p) => p.id === packSel) ?? packs?.[0];
  const packId = pack?.id ?? "";
  const region = pack && regionSel && pack.regions.includes(regionSel) ? regionSel : (pack?.regions[0] ?? "");
  const setting = pack && settingSel && pack.settings.includes(settingSel) ? settingSel : (pack?.settings.includes("rural") ? "rural" : (pack?.settings[0] ?? "rural"));
  const script = pack && scriptSel && pack.scripts.some((s) => s.id === scriptSel) ? scriptSel : (pack?.default_script ?? "");
  const choosePack = (id: string) => { setPackSel(id); setRegionSel(null); setSettingSel(null); setScriptSel(null); };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const form = new FormData();
      form.set("pack_id", packId);
      form.set("region", region);
      form.set("setting", setting);
      form.set("output_script", script);
      if (mode === "upload" && file) form.set("file", file);
      else form.set("text", text);
      const created = await api.create(form);
      toast.success(`Uploaded: ${created.scenes} scenes found${created.problems.length ? `, ${created.problems.length} note(s)` : ""}`);
      router.push(`/projects/${created.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  async function loadSample() {
    setText(await (await fetch("/demo/sample_screenplay.txt")).text());
    setMode("paste");
  }

  const ready = (mode === "paste" ? text.trim().length > 0 : !!file) && !!packId && !!region && !!script;

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <PageHeader eyebrow="New adaptation" title="Choose a screenplay and an exact culture" description="Be specific: the dialect and region decide the names, speech, clothing and setting the model is grounded on." />
      <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[1.35fr_1fr]">
        <section className="rounded-2xl border bg-card p-5 shadow-card sm:p-6">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-lg font-medium">1. Screenplay</h2>
            <Button type="button" variant="ghost" size="sm" onClick={loadSample}><Sparkles aria-hidden /> Use the sample screenplay</Button>
          </div>
          <div role="tablist" aria-label="Input method" className="mb-4 inline-flex rounded-lg bg-muted p-1">
            {([["paste", "Paste text", ClipboardPaste], ["upload", "Upload file", Upload]] as const).map(([k, label, Icon]) => (
              <button key={k} type="button" role="tab" aria-selected={mode === k} onClick={() => setMode(k)}
                className={cn("flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors", mode === k ? "bg-card shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                <Icon className="size-4" aria-hidden /> {label}
              </button>
            ))}
          </div>
          {mode === "paste" ? (
            <Field label="Screenplay text" htmlFor="text" hint="Scenes start with a heading such as “INT. KITCHEN - DAY”. 3 to 5 scenes work best.">
              <Textarea id="text" value={text} onChange={(e) => setText(e.target.value)} rows={16} placeholder={"INT. FAMILY HOME - KITCHEN - MORNING\n\nMEERA (58) stirs a pot..."} className="screenplay min-h-72 text-[13px]" />
            </Field>
          ) : (
            <Field label="TXT, DOCX or PDF" htmlFor="file" hint="Scanned PDFs without text cannot be read.">
              <label htmlFor="file" className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed bg-paper px-6 py-14 text-center transition-colors hover:border-primary/50 hover:bg-accent/50 focus-within:border-primary">
                <FileText className="size-8 text-primary" aria-hidden />
                <span className="text-sm font-medium">{file ? file.name : "Choose a file"}</span>
                <span className="text-xs text-muted-foreground">{file ? `${(file.size / 1024).toFixed(1)} KB` : "or drop it here"}</span>
                <input id="file" type="file" accept=".txt,.docx,.pdf" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </label>
            </Field>
          )}
        </section>

        <section className="space-y-5 rounded-2xl border bg-card p-5 shadow-card sm:p-6">
          <h2 className="text-lg font-medium">2. Culture</h2>
          {packsError && <p className="rounded-lg border border-danger-line bg-danger-soft p-3 text-sm text-danger">{errorMessage(packsError)}</p>}
          <Field label="Culture and dialect" htmlFor="pack">
            <select id="pack" className={select} value={packId} onChange={(e) => choosePack(e.target.value)}>
              {packs?.map((p) => <option key={p.id} value={p.id}>{p.culture}</option>)}
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Region" htmlFor="region">
              <select id="region" className={select} value={region} onChange={(e) => setRegionSel(e.target.value)}>{pack?.regions.map((r) => <option key={r}>{r}</option>)}</select>
            </Field>
            <Field label="Setting" htmlFor="setting">
              <select id="setting" className={select} value={setting} onChange={(e) => setSettingSel(e.target.value)}>{pack?.settings.map((s) => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}</select>
            </Field>
          </div>
          <Field label="Output script" htmlFor="script" hint="The script the adapted screenplay is written in, including character names.">
            <select id="script" className={select} value={script} onChange={(e) => setScriptSel(e.target.value)}>{pack?.scripts.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</select>
          </Field>
          {pack && pack.avoid_mixing_with.length > 0 && (
            <p className="flex flex-wrap items-center gap-1 rounded-xl bg-paper p-3.5 text-xs text-muted-foreground">Kept apart from: {pack.avoid_mixing_with.map((a) => <Chip key={a}>{a}</Chip>)}</p>
          )}
        </section>

        <div className="lg:col-span-2">
          {error && <p role="alert" className="mb-3 flex items-start gap-2 rounded-lg border border-danger-line bg-danger-soft p-3 text-sm text-danger"><AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />{error}</p>}
          <Button type="submit" size="lg" className="h-11 px-6 text-[15px]" disabled={!ready || busy}>
            {busy && <Loader2 className="animate-spin" aria-hidden />} Upload and continue
          </Button>
        </div>
      </form>
    </div>
  );
}
