import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/api/client";
import { keys, planKey } from "@/api/queries";
import type { Project, Settings } from "@/api/types";

const DELAY = 700; // typing: save once the user pauses
const POOL_KEYS = ["people", "date_from", "date_to", "album_id", "videos"];
const PLAN_KEYS = ["pace", "motion"];

/**
 * Project settings with optimistic updates: the page shows a change at once; saving is debounced for typing
 * (`set(..., {debounce: true})`) and immediate otherwise. Pending changes are merged, and `flush()` saves them
 * right away; every action that reads the settings on the server (suggest, render...) must await it first.
 */
export function useSettings(pid: string) {
  const qc = useQueryClient();
  const pending = useRef<Partial<Settings>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inflight = useRef<Promise<void>>(Promise.resolve());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const flush = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const body = pending.current;
    pending.current = {};
    const run = async () => {
      if (!Object.keys(body).length) return;
      setSaving(true);
      try {
        const p = await api.patch<Project>(`/api/projects/${pid}`, body);
        // the answer is the stored project (no running/history…): merge it over the cached view, keep the
        // fields still pending (typed while this request was out) on top, then refetch the full view
        qc.setQueryData<Project>(keys.project(pid), (old) => ({ ...(old ?? p), ...p, ...pending.current }));
        void qc.invalidateQueries({ queryKey: keys.project(pid) });
        // pace rebuilds the shots and motion changes the camera moves: the plan is stale
        if (PLAN_KEYS.some((k) => k in body)) void qc.invalidateQueries({ queryKey: planKey(pid) });
        setError(null);
        // new people / dates / album / videos: the server starts analysing those photos on the GPU a moment later
        if (POOL_KEYS.some((k) => k in body))
          setTimeout(() => void qc.invalidateQueries({ queryKey: keys.project(pid) }), 3000);
      } catch (e) {
        const status = e instanceof ApiError ? e.status : 0;
        // refused as invalid (too long, bad date, blocked project): drop it, or it would ride along with every
        // later change and get all of them refused too; the screen goes back to what is saved.
        // Network trouble, a job in the way (409) or a server error: keep it and retry with the next change.
        const refused = status >= 400 && status < 500 && status !== 409;
        if (!refused) pending.current = { ...body, ...pending.current };
        setError((e as Error).message);
        void qc.invalidateQueries({ queryKey: keys.project(pid) });
        throw e;
      } finally {
        setSaving(false);
      }
    };
    inflight.current = inflight.current.catch(() => {}).then(run); // one request at a time, in order
    return inflight.current;
  }, [pid, qc]);

  const set = useCallback(
    (change: Partial<Settings>, opts: { debounce?: boolean } = {}) => {
      pending.current = { ...pending.current, ...change };
      qc.setQueryData<Project>(keys.project(pid), (old) => (old ? { ...old, ...change } : old));
      if (timer.current) clearTimeout(timer.current);
      if (opts.debounce) timer.current = setTimeout(() => void flush().catch(() => {}), DELAY);
      else void flush().catch(() => {});
    },
    [flush, pid, qc],
  );

  // a refetch while a job runs must not undo what is typed but not saved yet: put the pending fields back on top
  useEffect(
    () =>
      qc.getQueryCache().subscribe((ev) => {
        if (ev.type !== "updated" || ev.action.type !== "success") return;
        const key = ev.query.queryKey;
        if (key[0] !== "project" || key[1] !== pid) return;
        const data = ev.query.state.data as Project | undefined;
        const pend = pending.current as Record<string, unknown>;
        if (!data || !Object.keys(pend).length) return;
        if (Object.entries(pend).some(([k, v]) => (data as unknown as Record<string, unknown>)[k] !== v))
          qc.setQueryData<Project>(keys.project(pid), { ...data, ...pending.current });
      }),
    [qc, pid],
  );

  // leaving the page, or the app going to the background (a phone may kill it there without notice), with
  // something typed: save it now (keepalive survives the unload)
  useEffect(() => {
    const onHide = () => {
      if (!Object.keys(pending.current).length) return;
      if (timer.current) clearTimeout(timer.current);
      void fetch(`/api/projects/${pid}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(pending.current),
        keepalive: true,
      });
      pending.current = {};
    };
    const onVisibility = () => {
      if (document.hidden) onHide();
    };
    window.addEventListener("pagehide", onHide);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("pagehide", onHide);
      document.removeEventListener("visibilitychange", onVisibility);
      onHide();
    };
  }, [pid]);

  return { set, flush, saving, error };
}
