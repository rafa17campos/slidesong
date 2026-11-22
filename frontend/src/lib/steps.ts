import type { JobKind, Project } from "@/api/types";
import i18n from "@/i18n";

export const STEPS = ["song", "photos", "storyboard", "video"] as const;
export type Step = (typeof STEPS)[number];

/** «Song», «Photos»… in the interface language. */
export const stepLabel = (step: Step) => i18n.t(`common:steps.${step}`);

const JOB_STEP: Record<JobKind, Step> = {
  analyze: "song",
  suggest: "photos",
  render: "video",
  export: "video",
};

/** The step addresses before the rename (old bookmarks and shared links): /montaje?plano=3 → /storyboard?shot=3 */
const LEGACY_STEP: Record<string, Step> = { cancion: "song", fotos: "photos", montaje: "storyboard" };
const LEGACY_PARAM: Record<string, string> = { plano: "shot", intercambio: "swap", revisar: "review" };

export function legacyStepUrl(pid: string, step: string | undefined, search: string): string | null {
  const to = step ? LEGACY_STEP[step] : undefined;
  if (!to) return null;
  const q = new URLSearchParams();
  for (const [k, v] of new URLSearchParams(search)) q.set(LEGACY_PARAM[k] ?? k, v);
  return `/p/${pid}/${to}${q.size ? `?${q}` : ""}`;
}

export const isStep = (s: string | undefined): s is Step => !!s && (STEPS as readonly string[]).includes(s);

export type StepState = "todo" | "done" | "working";

export function stepState(p: Project, step: Step): StepState {
  if (p.running && JOB_STEP[p.running] === step) return "working";
  const analyzed = p.slots.length > 0;
  const suggested = p.slots.some((s) => s.asset);
  switch (step) {
    case "song":
      return analyzed ? "done" : "todo";
    case "photos":
      return suggested ? "done" : "todo";
    case "storyboard":
      return suggested && p.slots.every((s) => s.asset) ? "done" : "todo";
    case "video":
      return p.renders.length > 0 ? "done" : "todo";
  }
}

/**
 * Where to land when a project is opened:
 * a running job's step; else, while the project is not set up yet (no song analyzed or no photos), the first
 * step still to do; else the step last visited in this project (remembered in the browser); else the storyboard.
 */
export function initialStep(p: Project, lastVisited: string | null): Step {
  if (p.running) return JOB_STEP[p.running];
  if (!p.slots.length) return "song";
  if (!p.slots.some((s) => s.asset)) return "photos";
  return isStep(lastVisited ?? undefined) ? (lastVisited as Step) : "storyboard";
}

const key = (pid: string) => `slidesong:step:${pid}`;

export function rememberStep(pid: string, step: Step) {
  try {
    localStorage.setItem(key(pid), step);
  } catch {
    /* storage unavailable: just don't remember */
  }
}

export function lastStep(pid: string): string | null {
  try {
    return localStorage.getItem(key(pid));
  } catch {
    return null;
  }
}
