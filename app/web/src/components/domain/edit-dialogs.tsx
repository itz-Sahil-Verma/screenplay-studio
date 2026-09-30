"use client";

import { GitMerge, Pencil } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { useAct } from "@/lib/hooks";
import type { Character } from "@/lib/types";
import { Spinner } from "./bits";
import { useWorkspace } from "./workspace";

const select = "h-10 w-full rounded-lg border border-input bg-card px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40";

const scenesMsg = (r: unknown) => {
  const s = (r as { affected_scenes: string[] }).affected_scenes;
  return s.length ? `Saved. Affects ${s.map((x) => `scene ${Number(x.slice(2))}`).join(", ")}: only those need regenerating.` : "Saved.";
};

export function EditCharacterButton({ character }: { character: Character }) {
  const { id } = useWorkspace();
  const act = useAct(id);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(character.name);
  const [role, setRole] = useState(character.role);
  const [age, setAge] = useState(character.age?.toString() ?? "");
  const [aliases, setAliases] = useState(character.aliases.join(", "));

  const save = () =>
    act.mutate(
      { run: () => api.editCharacter(id, character.id, { name, role, age: age ? Number(age) : null, aliases: aliases.split(",").map((a) => a.trim()).filter(Boolean) }), ok: scenesMsg },
      { onSuccess: () => setOpen(false) },
    );

  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)} aria-label={`Edit ${character.name}`}><Pencil aria-hidden /> Edit</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit {character.name}</DialogTitle>
            <DialogDescription>Correct what the model got wrong. Approvals are cleared and the continuity check re-runs.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="space-y-1.5"><Label htmlFor="e-name">Name</Label><Input id="e-name" value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2 space-y-1.5"><Label htmlFor="e-role">Role</Label><Input id="e-role" value={role} onChange={(e) => setRole(e.target.value)} /></div>
              <div className="space-y-1.5"><Label htmlFor="e-age">Age</Label><Input id="e-age" inputMode="numeric" value={age} onChange={(e) => setAge(e.target.value)} /></div>
            </div>
            <div className="space-y-1.5"><Label htmlFor="e-al">Other names (comma separated)</Label><Input id="e-al" value={aliases} onChange={(e) => setAliases(e.target.value)} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={save} disabled={act.isPending || !name.trim()}>{act.isPending && <Spinner />} Save changes</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export function MergeButton({ kind, record, options }: { kind: "character" | "prop" | "location" | "costume"; record: { id: string; name: string }; options: { id: string; name: string }[] }) {
  const { id } = useWorkspace();
  const act = useAct(id);
  const [open, setOpen] = useState(false);
  const [keep, setKeep] = useState("");
  const others = options.filter((o) => o.id !== record.id);
  if (!others.length) return null;

  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => { setKeep(others[0].id); setOpen(true); }} aria-label={`Merge ${record.name} into another ${kind}`}><GitMerge aria-hidden /> Merge</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Merge “{record.name}” into another {kind}</DialogTitle>
            <DialogDescription>Every reference follows. Two characters who appear in the same scene cannot be merged: they are different people.</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="m-keep">Keep this {kind}</Label>
            <select id="m-keep" className={select} value={keep} onChange={(e) => setKeep(e.target.value)}>
              {others.map((o) => <option key={o.id} value={o.id}>{o.name} ({o.id})</option>)}
            </select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => act.mutate({ run: () => api.merge(id, kind, keep, record.id), ok: scenesMsg }, { onSuccess: () => setOpen(false) })} disabled={act.isPending || !keep}>
              {act.isPending && <Spinner />} Merge
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
