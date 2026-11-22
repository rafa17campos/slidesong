import { CircleAlert, CirclePause, LoaderCircle, ScanFace, X } from "lucide-react";

import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { useCancelJob } from "@/api/queries";
import type { Project } from "@/api/types";
import { currentJob, fmtClock, fmtLeft, jobLabel, jobTiming, noticeKey } from "@/lib/jobs";

const DISMISSED = "slidesong:dismissed-errors";
const readDismissed = (): string[] => {
  try {
    return JSON.parse(localStorage.getItem(DISMISSED) ?? "[]");
  } catch {
    return [];
  }
};

/** Remember a dismissed notice (the last 50); returns the new list. */
function remember(key: string): string[] {
  const next = [...readDismissed(), key].slice(-50);
  try {
    localStorage.setItem(DISMISSED, JSON.stringify(next));
  } catch {
    /* only for this visit */
  }
  return next;
}

export function JobBar({ project: p }: { project: Project }) {
  const { t } = useTranslation(["project", "common"]);
  const cancel = useCancelJob(p.id);
  const [dismissed, setDismissed] = useState(readDismissed);
  const cur = currentJob(p, dismissed);
  const key = cur ? noticeKey(p.id, cur.kind, cur.job) : "";
  const dismiss = () => setDismissed(remember(key));
  // a cancel notice goes away by itself after 20 s (nothing is polled once the job has stopped)
  const cancelled = cur?.job.state === "cancelled";
  useEffect(() => {
    if (!cancelled) return;
    const h = setTimeout(() => setDismissed(remember(key)), 20_000);
    return () => clearTimeout(h);
  }, [cancelled, key]);
  const prep = p.prep?.state === "running" && p.prep.total ? p.prep : null;
  const local = cur?.job.where && cur.job.remote === false ? cur.job.where : null;
  return (
    <>
      {cur?.job.state === "running" && !p.cancelling && (
        <div className="jobbar" role="status">
          <LoaderCircle className="ico spin jic" aria-hidden />
          <span className="what">{jobLabel(cur.kind)}</span>
          {cur.job.where && (
            <span className="muted hide-mobile">
              {cur.job.waiting
                ? t("job.waiting", { where: cur.job.where })
                : t("job.where", { where: cur.job.where })}
            </span>
          )}
          <div className="track" aria-hidden>
            <i style={{ width: `${Math.round(cur.job.progress * 100)}%` }} />
          </div>
          <span className="nums">
            <span className="pct">{Math.round(cur.job.progress * 100)} %</span> <Timing project={p} />
          </span>
          <button
            type="button"
            className="btn sm ghost cancel"
            aria-label={t("job.cancel", { job: jobLabel(cur.kind) })}
            onClick={() => cancel.mutate()}
            disabled={cancel.isPending}
          >
            <X className="ico ico-sm" aria-hidden />
            <span className="hide-mobile">{t("common:actions.cancel")}</span>
          </button>
          {local && <span className="sr-only">{t("job.runningOn", { where: local })}</span>}
        </div>
      )}
      {cur?.job.state === "running" && p.cancelling && (
        <div className="jobbar cancelled" role="status">
          <LoaderCircle className="ico spin jic" aria-hidden />
          <span className="what">{t("job.cancelling", { job: jobLabel(cur.kind) })}</span>
          <span className="nums muted">{t("job.nothingHalfDone")}</span>
        </div>
      )}
      {cur?.job.state === "cancelled" && (
        <div className="jobbar cancelled" role="status">
          <CirclePause className="ico jic muted" aria-hidden />
          <span className="what">{t("job.cancelled", { job: jobLabel(cur.kind) })}</span>
          <span className="nums muted">{t("job.unchanged")}</span>
          <button
            type="button"
            className="icon-btn sm bare cancel"
            aria-label={t("job.closeNotice")}
            onClick={dismiss}
          >
            <X className="ico" />
          </button>
        </div>
      )}
      {cur?.job.state === "error" && (
        <div className="jobbar err" role="alert">
          <CircleAlert className="ico jic danger-text" aria-hidden />
          <span className="what">{t("job.failed", { job: jobLabel(cur.kind) })}</span>
          <details className="nums muted">
            <summary>{t("job.details")}</summary>
            {cur.job.error}
          </details>
          <button
            type="button"
            className="icon-btn sm bare cancel"
            aria-label={t("job.closeNotice")}
            onClick={dismiss}
          >
            <X className="ico" />
          </button>
        </div>
      )}
      {prep && (
        <div className="jobbar prep" role="status">
          <ScanFace className="ico muted" aria-hidden />
          <span className="muted">
            <Trans t={t} i18nKey="job.prep" components={{ span: <span className="hide-mobile" /> }} />
          </span>
          <span className="strong tnum">
            {t("job.prepCount", { done: prep.done ?? 0, total: prep.total })}
          </span>
          <div className="track" aria-hidden>
            <i style={{ width: `${Math.round(((prep.done ?? 0) / (prep.total ?? 1)) * 100)}%` }} />
          </div>
        </div>
      )}
    </>
  );
}

function Timing({ project: p }: { project: Project }) {
  const { t } = useTranslation(["project", "common"]);
  const j = p.running ? p.jobs[p.running] : undefined;
  const time = j && jobTiming(j.started, j.progress, p.server_now);
  if (!time) return null;
  return (
    <span className="eta">
      {fmtClock(time.elapsed)}
      {time.left != null && t("job.left", { left: fmtLeft(time.left) })}
    </span>
  );
}
