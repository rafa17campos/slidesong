import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { api } from "./client";
import type {
  BackupInfo,
  Coverage,
  Album,
  JobKind,
  Learning,
  LearningDetail,
  LearningEvent,
  Person,
  Plan,
  Project,
  ProjectSummary,
  Settings,
  WorkerStatus,
} from "./types";

export const keys = {
  projects: ["projects"] as const,
  project: (pid: string) => ["project", pid] as const,
  worker: ["worker"] as const,
  people: ["people"] as const,
};

export const useProjects = () =>
  useQuery({
    queryKey: keys.projects,
    queryFn: ({ signal }) => api.get<ProjectSummary[]>("/api/projects", signal),
    refetchInterval: (q) => (q.state.data?.some((p) => p.running) ? 3000 : false),
  });

export const useWorker = () =>
  useQuery({
    queryKey: keys.worker,
    queryFn: ({ signal }) => api.get<WorkerStatus>("/api/worker", signal),
    refetchInterval: 30_000,
  });

export const usePeople = () =>
  useQuery({
    queryKey: keys.people,
    queryFn: ({ signal }) => api.get<Person[]>("/api/people", signal),
    staleTime: 10 * 60_000,
  });

/** The project; polled while a job or the background photo analysis runs. */
export function useProject(pid: string) {
  const q = useQuery({
    queryKey: keys.project(pid),
    queryFn: ({ signal }) => api.get<Project>(`/api/projects/${pid}`, signal),
    refetchInterval: (query) => {
      const p = query.state.data;
      return p && (p.running || p.prep?.state === "running" || p.cancelling) ? 1500 : false;
    },
  });
  // a job that changes the shots just ended: the plan is stale
  const qc = useQueryClient();
  const running = q.data?.running ?? null;
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running) void qc.invalidateQueries({ queryKey: planKey(pid) });
    wasRunning.current = running;
  }, [running, pid, qc]);
  // the project changed (also from another device): its plan may be stale
  const rev = q.data?.edit_rev;
  const lastRev = useRef(rev);
  useEffect(() => {
    if (lastRev.current !== undefined && rev !== lastRev.current)
      void qc.invalidateQueries({ queryKey: planKey(pid) });
    lastRev.current = rev;
  }, [rev, pid, qc]);
  // back from another app or tab: catch up at once (a job may have finished meanwhile)
  const { refetch } = q;
  useEffect(() => {
    const onShow = () => {
      if (!document.hidden) void refetch();
    };
    document.addEventListener("visibilitychange", onShow);
    window.addEventListener("pageshow", onShow);
    return () => {
      document.removeEventListener("visibilitychange", onShow);
      window.removeEventListener("pageshow", onShow);
    };
  }, [refetch]);
  return q;
}

/**
 * What an edit endpoint answers is the stored project: it lacks what GET adds (running, history, prep…).
 * Merge it over the cached view (never replace it, or undo and the job bar would vanish), then refetch the
 * full view; and the plan, when the shots may have changed.
 */
export function applyProject(qc: QueryClient, pid: string, doc: unknown, opts: { plan?: boolean } = {}) {
  if (doc && typeof doc === "object" && "slots" in doc)
    qc.setQueryData<Project>(keys.project(pid), (old) =>
      old ? { ...old, ...(doc as Partial<Project>) } : (doc as Project),
    );
  void qc.invalidateQueries({ queryKey: keys.project(pid) });
  if (opts.plan !== false) void qc.invalidateQueries({ queryKey: planKey(pid) });
}

/** Any call that returns the updated project (merged into the cache, see applyProject). */
export function useProjectMutation<V, R = Project>(pid: string, call: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (data) => applyProject(qc, pid, data),
  });
}

export const useSaveSettings = (pid: string) =>
  useProjectMutation(pid, (s: Partial<Settings>) => api.patch<Project>(`/api/projects/${pid}`, s));

const JOB_URL: Record<JobKind, string> = {
  analyze: "analyze",
  suggest: "suggest",
  render: "render",
  export: "export",
};

export function useStartJob(pid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, query }: { kind: JobKind; query?: Record<string, string> }) =>
      api.post(`/api/projects/${pid}/${JOB_URL[kind]}${query ? `?${new URLSearchParams(query)}` : ""}`),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.project(pid) }),
  });
}

export function useCancelJob(pid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post(`/api/projects/${pid}/cancel`),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.project(pid) }),
  });
}

/** Undo / redo one step (server-side history); the response is the restored project. */
export function useHistoryStep(pid: string) {
  // {dir: "undo", rev}: undo only if no other edit came after the one with that edit_rev (a toast's «Undo»)
  return useProjectMutation(pid, (arg: "undo" | "redo" | { dir: "undo"; rev?: number }) => {
    const dir = typeof arg === "string" ? arg : arg.dir;
    const rev = typeof arg === "string" ? undefined : arg.rev;
    return api.post<Project & { undone?: string; redone?: string }>(
      `/api/projects/${pid}/${dir}${rev != null ? `?expect_rev=${rev}` : ""}`,
    );
  });
}

// ---------------- plan (camera moves, transitions, warnings) ----------------

export const planKey = (pid: string) => ["plan", pid] as const;

/** The edit plan; refetched after anything that changes the shots (see useProjectMutation / useProject). */
export const usePlan = (pid: string, enabled = true) =>
  useQuery({
    queryKey: planKey(pid),
    queryFn: ({ signal }) => api.get<Plan>(`/api/projects/${pid}/plan`, signal),
    enabled,
    staleTime: Infinity,
  });

/** A change that answers with the new plan (camera move, transition, second photo, caption, amount of move). */
export function usePlanMutation<V>(pid: string, call: (v: V) => Promise<Plan>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (plan) => {
      qc.setQueryData(planKey(pid), plan);
      void qc.invalidateQueries({ queryKey: keys.project(pid) }); // overrides + undo label
    },
  });
}

export const useConfig = () =>
  useQuery({
    queryKey: ["config"],
    queryFn: ({ signal }) =>
      api.get<{ immich_web: string; song_languages: string[]; assistant_refs: boolean; source_url: string }>(
        "/api/config",
        signal,
      ),
    staleTime: Infinity,
  });

export const useAlbums = (enabled = true) =>
  useQuery({
    queryKey: ["albums"],
    queryFn: ({ signal }) => api.get<Album[]>("/api/albums", signal),
    enabled,
    staleTime: 60_000,
  });

export const useLearning = () =>
  useQuery({ queryKey: ["learning"], queryFn: ({ signal }) => api.get<Learning>("/api/learning", signal) });

export const learningDetailKey = ["learning-detail"] as const;

/** The «Learning» page; polled while the weights are being fitted again. */
export const useLearningDetail = () =>
  useQuery({
    queryKey: learningDetailKey,
    queryFn: ({ signal }) => api.get<LearningDetail>("/api/learning/detail", signal),
    refetchInterval: (q) => (q.state.data?.status.running ? 3000 : false),
  });

export const useLearningEvents = (project: string, accepted: boolean) =>
  useInfiniteQuery({
    queryKey: ["learning-events", project, accepted],
    queryFn: ({ pageParam, signal }) =>
      api.get<{ total: number; events: LearningEvent[] }>(
        `/api/learning/events?${new URLSearchParams({
          offset: String(pageParam),
          limit: "30",
          accepted: String(accepted),
          ...(project ? { project } : {}),
        })}`,
        signal,
      ),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const n = pages.reduce((a, p) => a + p.events.length, 0);
      return n < last.total ? n : undefined;
    },
  });

export const coverageKey = (p: Project) =>
  ["coverage", p.id, p.people, p.date_from, p.date_to, p.album_id, p.videos, p.prep?.state ?? null] as const;

export const fetchCoverage = (pid: string, signal?: AbortSignal) =>
  api.get<Coverage>(`/api/projects/${pid}/coverage`, signal);

/** Photos of the project not analysed on the GPU yet, and whether the worker can do it (for the warnings). */
export const useCoverage = (p: Project, enabled = true) =>
  useQuery({
    queryKey: coverageKey(p),
    queryFn: ({ signal }) => fetchCoverage(p.id, signal),
    enabled,
    staleTime: 30_000,
  });

export const backupInfoKey = ["backup-info"] as const;
export const useBackupInfo = (enabled = true) =>
  useQuery({
    queryKey: backupInfoKey,
    queryFn: ({ signal }) => api.get<BackupInfo>("/api/backup/info", signal),
    enabled,
  });
