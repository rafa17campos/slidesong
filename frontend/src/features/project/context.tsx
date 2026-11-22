import { createContext, useContext } from "react";

import type { Plan, Project } from "@/api/types";
import type { useSettings } from "@/hooks/useSettings";

export interface ProjectCtx {
  project: Project;
  plan: Plan | undefined;
  settings: ReturnType<typeof useSettings>;
  /** Run one of the project's jobs, saving pending settings first and asking where it matters. */
  analyze: () => Promise<void>;
  suggest: () => Promise<void>;
  render: (quality: "preview" | "final" | "final2k" | "final4k") => Promise<void>;
  exportZip: () => Promise<void>;
  busy: boolean;
  /** blocked project: everything is read-only except making videos */
  frozen: boolean;
  /** nothing can be edited now: blocked, or a job that rewrites the shots (analyse, suggest) is running */
  readOnly: boolean;
  /** the final quality chosen in ④ (the header's «Final video» uses it too) */
  quality: "final" | "final2k" | "final4k";
  setQuality: (q: "final" | "final2k" | "final4k") => void;
  newVersion: () => void;
}

export const Ctx = createContext<ProjectCtx | null>(null);

export function useProjectCtx(): ProjectCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useProjectCtx outside a project page");
  return c;
}
