"use client";

import { Pencil } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useAct } from "@/lib/hooks";
import { Spinner } from "./bits";
import { useWorkspace } from "./workspace";

export type PlanField = { key: string; label: string; long?: boolean; native?: boolean };

/** Correct the model's plan for one character/costume/place/prop. The server re-verifies it and marks affected scenes. */
export function EditPlanButton({ kind, entityId, title, fields, values }: { kind: "character" | "costume" | "location" | "prop"; entityId: string; title: string; fields: PlanField[]; values: Record<string, string> }) {
  const { id, demo } = useWorkspace();
  const act = useAct(id);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(values);
  if (demo) return null;

  const save = () =>
    act.mutate(
      { run: () => api.editPlan(id, kind, entityId, form), ok: (r) => { const s = (r as { affected_scenes: string[] }).affected_scenes; return s.length ? `Saved. Scene plans for ${s.map((x) => Number(x.slice(2))).join(", ")} are now stale: re-plan them or keep them.` : "Saved."; } },
      { onSuccess: () => setOpen(false) },
    );

  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => { setForm(values); setOpen(true); }} aria-label={`Edit ${title}`}><Pencil aria-hidden /> Edit</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Edit {title}</DialogTitle>
            <DialogDescription>The plan is re-checked after you save (script, names, duplicates). Scenes it touches will need re-planning or an explicit “keep”.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            {fields.map((f) => (
              <div key={f.key} className="space-y-1.5">
                <Label htmlFor={`f-${f.key}`}>{f.label}</Label>
                {f.long ? <Textarea id={`f-${f.key}`} rows={3} value={form[f.key] ?? ""} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
                  : <Input id={`f-${f.key}`} className={f.native ? "gurmukhi" : undefined} value={form[f.key] ?? ""} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />}
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={save} disabled={act.isPending}>{act.isPending && <Spinner />} Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
