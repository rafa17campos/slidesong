// Every edit of a shot, as mutations that refresh the project (and its plan) with the server's answer.
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { usePlanMutation, useProjectMutation } from "@/api/queries";
import type { BurstPhoto, Partner, Plan, Project } from "@/api/types";

export interface SlotChange {
  action: "set" | "reject" | "lock" | "unlock" | "clip";
  asset?: string;
  why?: string[];
  source?: string;
  shown?: string[];
  clip_start?: number | null;
  /** the photo the user saw in the shot (the server refuses if it changed meanwhile) */
  expect?: string;
}

export function useShotActions(pid: string) {
  const base = `/api/projects/${pid}`;
  return {
    slot: useProjectMutation(pid, ({ i, change }: { i: number; change: SlotChange }) =>
      api.post<Project>(`${base}/slots/${i}`, change),
    ),
    exchange: useProjectMutation(pid, ({ a, b }: { a: number; b: number }) =>
      api.post<Project>(`${base}/exchange`, { a, b }),
    ),
    subs: useProjectMutation(pid, ({ i, on }: { i: number; on: boolean }) =>
      api.post<Project>(`${base}/slots/${i}/subs`, { on }),
    ),
    look: usePlanMutation(pid, ({ slot, kind }: { slot: number; kind: string | null }) =>
      api.post<Plan>(`${base}/shots/${slot}`, { kind }),
    ),
    move: usePlanMutation(pid, ({ slot, factor }: { slot: number; factor: number | null }) =>
      api.post<Plan>(`${base}/shots/${slot}/move`, { factor }),
    ),
    pair: usePlanMutation(pid, ({ i, asset }: { i: number; asset: string | null }) =>
      api.post<Plan>(`${base}/slots/${i}/pair`, { asset }),
    ),
    caption: usePlanMutation(pid, ({ asset, text }: { asset: string; text: string | null }) =>
      api.post<Plan>(`${base}/captions`, { asset, text }),
    ),
    transition: usePlanMutation(pid, ({ after, kind }: { after: number; kind: string | null }) =>
      api.post<Plan>(`${base}/transitions/${after}`, { kind }),
    ),
  };
}

/** The photos of the same moment as the shot's photo (computed lazily by the server). */
export const useBurst = (pid: string, i: number, asset: string | null, enabled: boolean) =>
  useQuery({
    queryKey: ["burst", pid, i, asset],
    queryFn: ({ signal }) => api.get<BurstPhoto[]>(`/api/projects/${pid}/slots/${i}/burst`, signal),
    enabled: enabled && !!asset,
    staleTime: 5 * 60_000,
  });

export const usePartners = (pid: string, i: number, enabled: boolean) =>
  useQuery({
    queryKey: ["partners", pid, i],
    queryFn: ({ signal }) => api.get<Partner[]>(`/api/projects/${pid}/slots/${i}/partners`, signal),
    enabled,
  });

/** ~6 s of video around a shot (made on demand on the server). */
export const makeSnippet = (pid: string, i: number) =>
  api.post<{ file: string; from: number; to: number }>(`/api/projects/${pid}/slots/${i}/snippet`);

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;

/** The photo id in a pasted Immich link (the last UUID: album links carry the album's first). */
export function immichIdFrom(text: string): string | null {
  const all = text.match(UUID);
  return all ? all[all.length - 1]!.toLowerCase() : null;
}
