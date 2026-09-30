import type { Project } from "@/lib/types";
import { cn } from "@/lib/utils";

const TITLES = new Set(["mr.", "mrs.", "ms.", "dr.", "mr", "mrs", "ms", "dr"]);
/** First name, skipping a title: "Mr. Desai" is Desai, not "Mr.". */
const first = (s: string) => s.split(" ").find((w) => !TITLES.has(w.toLowerCase())) ?? s;

/** A scenes-by-things grid. Cells that a finding touches are tinted, so a contradiction is visible without reading. */
function Grid({ scenes, rows }: { scenes: { scene_id: string; number: number }[]; rows: { id: string; label: string; cell: (sid: string) => string; tint: (sid: string) => "danger" | "warning" | null }[] }) {
  return (
    <div className="overflow-x-auto rounded-2xl border bg-card shadow-card">
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead>
          <tr className="border-b bg-paper text-left text-xs uppercase tracking-wider text-muted-foreground">
            <th scope="col" className="px-4 py-2.5 font-semibold">&nbsp;</th>
            {scenes.map((s) => <th key={s.scene_id} scope="col" className="px-3 py-2.5 font-semibold">Scene {s.number}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b last:border-0">
              <th scope="row" className="whitespace-nowrap px-4 py-3 text-left font-medium">{r.label}</th>
              {scenes.map((s) => {
                const t = r.tint(s.scene_id);
                const v = r.cell(s.scene_id);
                return (
                  <td key={s.scene_id} className={cn("px-3 py-3", t === "danger" && "bg-danger-soft text-danger", t === "warning" && "bg-warning-soft text-warning", !v && "text-muted-foreground/60")}>
                    {v || "–"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PropGrid({ p }: { p: Project }) {
  const scenes = [...p.scenes].sort((a, b) => a.number - b.number);
  const name = (id: string) => (id.startsWith("@") ? id.slice(1) : first(p.characters.find((c) => c.id === id)?.name ?? id));
  const rows = p.props.filter((x) => x.scene_ids.length > 0).map((x) => ({
    id: x.id,
    label: x.name,
    cell: (sid: string) => {
      const s = scenes.find((z) => z.scene_id === sid)!;
      const a = s.prop_holder_start[x.id], b = s.prop_holder_end[x.id];
      if (!a && !b) return x.scene_ids.includes(sid) ? "present" : "";
      return a && b && a !== b ? `${name(a)} → ${name(b)}` : name(b || a);
    },
    tint: (sid: string) => {
      const hit = p.warnings.filter((w) => w.entity_id === x.id && w.affected_scene_ids.includes(sid) && w.severity !== "info");
      return hit.some((w) => w.severity === "error") ? ("danger" as const) : hit.length ? ("warning" as const) : null;
    },
  }));
  return <Grid scenes={scenes} rows={rows} />;
}

export function CostumeGrid({ p }: { p: Project }) {
  const scenes = [...p.scenes].sort((a, b) => a.number - b.number);
  const rows = p.characters.map((c) => ({
    id: c.id,
    label: first(c.name),
    cell: (sid: string) => {
      const id = scenes.find((s) => s.scene_id === sid)?.costumes[c.id];
      const k = p.costumes.find((x) => x.id === id);
      return id ? (k?.source_garments ?? k?.garments) || "not described" : "";
    },
    tint: (sid: string) => {
      const hit = p.warnings.filter((w) => w.code === "COSTUME_CHANGE_NO_REASON" && w.entity_id === c.id && w.affected_scene_ids.at(-1) === sid);
      return hit.length ? ("warning" as const) : null;
    },
  }));
  return <Grid scenes={scenes} rows={rows} />;
}
