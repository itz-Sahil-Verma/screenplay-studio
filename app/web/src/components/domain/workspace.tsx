"use client";

import { createContext, useContext } from "react";
import { DEMO_ID } from "@/lib/api";
import type { Project } from "@/lib/types";

type Ctx = { id: string; project: Project; demo: boolean };
const WorkspaceContext = createContext<Ctx | null>(null);

export const WorkspaceProvider = ({ id, project, children }: { id: string; project: Project; children: React.ReactNode }) => (
  <WorkspaceContext.Provider value={{ id, project, demo: id === DEMO_ID }}>{children}</WorkspaceContext.Provider>
);

/** The current project. Only usable inside /projects/[id]/..., where the layout has already loaded it. */
export function useWorkspace(): Ctx {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside a project page");
  return ctx;
}

export const prettyPack = (id: string) => id.split("_").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
