import type { JobKind, Project } from "@/api/types";
import i18n from "@/i18n";

/** «Analyzing the song»… */
export const jobLabel = (kind: JobKind): string => i18n.t(`terms:jobs.${kind}`);

export const fmtClock = (t: number) =>
  t >= 60 ? `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, "0")}` : `${Math.round(t)} s`;

/** Elapsed seconds and a rough estimate of what is left, from how fast progress has moved so far. */
export function jobTiming(started: string | undefined, progress: number, serverNow: string) {
  if (!started) return null;
  const elapsed = Math.max(0, (Date.parse(serverNow) - Date.parse(started)) / 1000);
  if (progress < 0.03 || elapsed < 4) return { elapsed, left: null };
  const left = (elapsed * (1 - progress)) / progress;
  return { elapsed, left };
}

export function fmtLeft(left: number) {
  return left < 60 ? `${Math.max(5, Math.round(left / 5) * 5)} s` : `${Math.round(left / 60)} min`;
}

/** The job to show in the bar: the running one, or one that just ended badly. */
/** Key of a finished job's notice, to remember it was dismissed. */
export const noticeKey = (pid: string, kind: string, job: { started?: string; finished?: string }) =>
  `${pid}:${kind}:${job.started ?? job.finished ?? ""}`;

/**
 * The job to show in the bar: the running one; else the most recent failure (a day at most) or cancel
 * (20 s at most) that has not been dismissed.
 */
export function currentJob(p: Project, dismissed: readonly string[] = []) {
  if (p.running) {
    const j = p.jobs[p.running];
    // just started: the job may still carry the state of its previous run (e.g. "cancelled") for a moment
    const job =
      j && j.state === "running" ? j : { state: "running" as const, progress: 0, error: null, where: null };
    return { kind: p.running, job };
  }
  const now = Date.parse(p.server_now);
  const ended = (Object.entries(p.jobs) as [JobKind, NonNullable<Project["jobs"][JobKind]>][])
    .filter(([kind, job]) => !dismissed.includes(noticeKey(p.id, kind, job)))
    .filter(
      ([, job]) =>
        (job.state === "error" && (!job.started || now - Date.parse(job.started) < 86_400_000)) ||
        (job.state === "cancelled" && job.finished && now - Date.parse(job.finished) < 20_000),
    )
    .sort(([, a], [, b]) => (b.finished ?? b.started ?? "").localeCompare(a.finished ?? a.started ?? ""));
  const [kind, job] = ended[0] ?? [];
  return kind && job ? { kind, job } : null;
}

export const isBusy = (p: Project) => !!p.running || p.prep?.state === "running";

/** Jobs that rewrite the shots when they end: no edits (nor undo) while they run. Renders and exports allow both. */
export const blocksEdits = (p: Pick<Project, "running">) =>
  p.running === "analyze" || p.running === "suggest";

/** How many edits the newest video is missing (0 = up to date; null = no video, or one too old to tell). */
/**
 * Whether the montage changed after the last video: compares what the video is made of (video_hash), so an edit
 * that was undone, or one that doesn't show in the video, doesn't count. Older videos only know the edit count.
 */
export function isStale(p: Project): boolean {
  const last = p.renders[0];
  if (!last) return false;
  if (last.vhash && p.video_hash) return last.vhash !== p.video_hash;
  return last.rev != null && (p.edit_rev ?? 0) > last.rev;
}
