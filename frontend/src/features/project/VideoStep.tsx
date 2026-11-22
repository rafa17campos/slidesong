import { useQueryClient } from "@tanstack/react-query";
import {
  Clapperboard,
  Download,
  Eye,
  LoaderCircle,
  Play,
  Scissors,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { Link } from "react-router";

import { api, assetUrl } from "@/api/client";
import { applyProject, useCancelJob, useWorker } from "@/api/queries";
import type { Project, RenderFile } from "@/api/types";
import { useConfirm } from "@/components/ui/Confirm";
import { useToast } from "@/components/ui/Toast";
import i18n, { locale } from "@/i18n";
import { fmtSize } from "@/lib/format";
import { isStale } from "@/lib/jobs";
import { fmtTime, open as openWarnings, warningsFor } from "@/lib/storyboard";

import { useProjectCtx } from "./context";

type Final = "final" | "final2k" | "final4k";

const QUALITIES = ["preview", "final", "final2k", "final4k"] as const;

/** «360p preview», «Final video 1080p · 60 fps»…; undefined for an unknown quality. */
const qualityName = (q: string): string | undefined =>
  (QUALITIES as readonly string[]).includes(q)
    ? i18n.t(`video:quality.${q as (typeof QUALITIES)[number]}`)
    : undefined;

/** «Today, 10:30», «Yesterday, 10:30», «Nov 3, 10:30»; `inline` for the middle of a sentence («from today, 10:30»). */
const fmtWhen = (d?: string, inline = false) => {
  if (!d) return "";
  const t = new Date(d);
  const today = new Date();
  const yest = new Date(today);
  yest.setDate(today.getDate() - 1);
  const time = t.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  if (t.toDateString() === today.toDateString())
    return i18n.t(inline ? "video:when.todayInline" : "video:when.today", { time });
  if (t.toDateString() === yest.toDateString())
    return i18n.t(inline ? "video:when.yesterdayInline" : "video:when.yesterday", { time });
  const date = t.toLocaleDateString(locale(), { day: "numeric", month: "short" });
  return i18n.t("video:when.date", { date, time });
};
const mins = (s: number) => (s < 90 ? "≈ 1 min" : `≈ ${Math.round(s / 60)} min`);

/** Rough time and size of each final, from the song's length (measured on an RTX 2070 worker: 1080p60 ≈ 1,3× the song). */
export function estimates(dur: number) {
  return {
    preview: { time: Math.max(30, dur * 0.25) },
    final: { time: dur * 1.35, size: dur * 1.3e6 },
    final2k: { time: dur * 2.3, size: dur * 2.3e6 },
    final4k: { time: dur * 5, size: dur * 4.5e6 },
  };
}

/** ④ Video: the player, creating previews and finals, exporting for an editor, and the files. */
export function VideoStep() {
  const { t } = useTranslation(["video", "common"]);
  const { project: p, plan, render, exportZip, busy, quality, setQuality } = useProjectCtx();
  const { data: worker } = useWorker();
  const open = p.slots.flatMap((_, i) => openWarnings(warningsFor(p, plan, i)));
  const toReview = p.slots.filter((_, i) => openWarnings(warningsFor(p, plan, i)).length > 0).length;
  const sensitive = open.filter((w) => w.kind === "sensitive").length;
  const [playing, setPlaying] = useState<string | null>(null);
  const photos = p.slots.some((s) => s.asset);
  const dur = p.song?.duration ?? 0;
  const est = estimates(dur);
  const current = p.renders.find((r) => r.file === playing) ?? p.renders[0];
  const stale = current === p.renders[0] && isStale(p);
  const disabled = busy || !photos;

  return (
    <main className="pg-video">
      <div className="wrap">
        <div className="col">
          {current ? (
            <>
              <section className="player" aria-label={t("common:steps.video")}>
                <video
                  key={current.file}
                  src={`/api/projects/${p.id}/files/${current.file}`}
                  controls
                  preload="metadata"
                  playsInline
                  poster={p.slots[0]?.asset ? assetUrl(p.slots[0].asset, "preview") : undefined}
                  style={{
                    display: "block",
                    width: "100%",
                    aspectRatio: "16 / 9",
                    background: "var(--color-stage)",
                  }}
                />
              </section>
              <div className="cap-row">
                <div className="grow">
                  <div className="strong">
                    {qualityName(current.quality ?? "preview") ?? t("common:steps.video")}
                  </div>
                  <div className="muted text-small tnum">
                    {[fmtWhen(current.created), dur ? fmtTime(dur) : "", fmtSize(current.size)]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </div>
                <a
                  className="btn sm ghost"
                  href={`/api/projects/${p.id}/files/${current.file}`}
                  download={`${p.title}-${current.quality ?? "video"}.mp4`}
                >
                  <Download className="ico ico-sm" aria-hidden />
                  {t("common:actions.download")}
                </a>
              </div>
              {stale && (
                <div className="callout warn">
                  <TriangleAlert className="ico" aria-hidden />
                  <div>
                    <Trans t={t} i18nKey="stale.text" components={{ b: <b /> }} />
                  </div>
                  <button
                    type="button"
                    className="btn sm warning"
                    disabled={disabled}
                    onClick={() => void render("preview")}
                  >
                    {t("stale.button")}
                  </button>
                </div>
              )}
            </>
          ) : (
            <section className="card-sunken p-6">
              <h2 className="font-display" style={{ margin: 0, fontSize: 26 }}>
                {t("empty.title")}
              </h2>
              <p className="muted" style={{ margin: "6px 0 0" }}>
                {photos ? t("empty.ready") : t("empty.noPhotos")}
              </p>
              {photos && (
                <button
                  type="button"
                  className="btn primary"
                  style={{ marginTop: 14 }}
                  disabled={busy}
                  onClick={() => void render("preview")}
                >
                  <Eye className="ico" aria-hidden /> {t("empty.button", { time: mins(est.preview.time) })}
                </button>
              )}
            </section>
          )}

          <Files project={p} playing={current?.file ?? null} onPlay={setPlaying} />
        </div>

        <aside className="col">
          <section className="card-elevated p-6" id="v-new-card" aria-labelledby="v-new">
            <div className="card-head">
              <h2 id="v-new">{t("create.title")}</h2>
            </div>
            <div className="opt-row">
              <span className="oi">
                <Eye className="ico" aria-hidden />
              </span>
              <div className="grow">
                <div className="strong text-small">{t("create.preview")}</div>
                <div className="muted text-caption">
                  {t("create.previewHint", { time: mins(est.preview.time) })}
                </div>
              </div>
              <button
                type="button"
                className="btn sm"
                disabled={disabled}
                onClick={() => void render("preview")}
              >
                {t("create.button")}
              </button>
            </div>
            <hr className="divider" />
            {toReview > 0 && !p.frozen && (
              <div className="callout warn" style={{ marginBottom: 12 }}>
                <TriangleAlert className="ico" aria-hidden />
                <div>
                  {sensitive
                    ? t("review.lineSensitive", {
                        shots: t("review.shots", { count: toReview }),
                        sensitive: t("review.sensitive", { count: sensitive }),
                      })
                    : t("review.line", { shots: t("review.shots", { count: toReview }) })}
                </div>
                <Link className="btn sm warning" to={`/p/${p.id}/storyboard?review=1`}>
                  {t("review.button")}
                </Link>
              </div>
            )}
            <div className="strong text-small" style={{ marginBottom: 8 }}>
              {t("create.final")}
            </div>
            <div className="q" role="radiogroup" aria-label={t("quality.label")}>
              {(
                [
                  ["final", "1080p", "60 fps"],
                  ["final2k", "2K", "1440p"],
                  ["final4k", "4K", t("quality.tv")],
                ] as [Final, string, string][]
              ).map(([k, name, d]) => (
                <button
                  key={k}
                  type="button"
                  role="radio"
                  aria-checked={quality === k}
                  onClick={() => setQuality(k)}
                >
                  <b>{name}</b>
                  <span>
                    {d} · {mins(est[k].time)}
                    <br />≈ {fmtSize(est[k].size)}
                  </span>
                </button>
              ))}
            </div>
            <button
              type="button"
              className="btn primary w-full"
              style={{ marginTop: 14 }}
              disabled={disabled}
              onClick={() => void render(quality)}
            >
              <Clapperboard className="ico" aria-hidden />
              {t("create.finalButton", {
                quality: { final: "1080p", final2k: "2K", final4k: "4K" }[quality],
              })}
            </button>
            <p className="text-caption muted" style={{ margin: "8px 2px 0", textAlign: "center" }}>
              {busy
                ? t("worker.busy")
                : worker && !worker.online
                  ? t("worker.offline", { name: worker.name })
                  : worker?.busy
                    ? t("worker.occupied", { name: worker.name })
                    : t("worker.runsOn", { name: worker?.name ?? t("worker.fallbackName") })}
            </p>
          </section>
          <section className="card-default p-6" id="v-exp-card" aria-labelledby="v-exp">
            <div className="card-head">
              <Scissors className="ico" aria-hidden />
              <h3 id="v-exp">{t("export.title")}</h3>
            </div>
            <p className="text-small secondary" style={{ margin: "0 0 14px" }}>
              {t("export.body")}
            </p>
            <button type="button" className="btn w-full" disabled={disabled} onClick={() => void exportZip()}>
              <Download className="ico" aria-hidden />
              {t("export.button")}
            </button>
          </section>
        </aside>
      </div>
    </main>
  );
}

function Files({
  project: p,
  playing,
  onPlay,
}: {
  project: Project;
  playing: string | null;
  onPlay: (f: string) => void;
}) {
  const { t } = useTranslation(["video", "common"]);
  const qc = useQueryClient();
  const toast = useToast();
  const cancel = useCancelJob(p.id);
  const [ask, confirmDialog] = useConfirm();
  const job = p.running === "render" || p.running === "export" ? p.jobs[p.running] : undefined;
  const items: (RenderFile & { kind: "render" | "export" })[] = [
    ...p.renders.map((r) => ({ ...r, kind: "render" as const })),
    ...(p.exports ?? []).map((r) => ({ ...r, kind: "export" as const })),
  ].sort((a, b) => (b.created ?? "").localeCompare(a.created ?? ""));
  if (!items.length && !job) return null;

  const remove = async (f: RenderFile & { kind: "render" | "export" }) => {
    const when = fmtWhen(f.created, true);
    const ok = await ask({
      title:
        f.kind === "export"
          ? t("files.delete.titleExport", { when })
          : t("files.delete.titleVideo", { name: qualityName(f.quality ?? "preview") ?? f.file, when }),
      body: t("files.delete.body"),
      confirm: t("common:actions.delete"),
      tone: "danger",
    });
    if (!ok) return;
    try {
      const r = await api.del<Project>(`/api/projects/${p.id}/files/${encodeURIComponent(f.file)}`);
      applyProject(qc, p.id, r, { plan: false });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };

  return (
    <section className="card-default p-6" id="v-files-card" aria-labelledby="v-files">
      <div className="card-head">
        <h3 id="v-files">{t("files.title")}</h3>
        <span className="badge">{items.length}</span>
      </div>
      <div className="files">
        {job && (
          <div className="file running">
            <span className="fi final">
              <LoaderCircle className="ico spin" aria-hidden />
            </span>
            <div>
              <div className="t">
                {p.running === "export" ? t("files.editable") : t("files.making")}{" "}
                <span className="badge info">{Math.round(job.progress * 100)} %</span>
              </div>
              <div className="track">
                <i style={{ width: `${Math.round(job.progress * 100)}%` }} />
              </div>
            </div>
            <div className="a">
              <button
                type="button"
                className="btn sm ghost"
                onClick={() => cancel.mutate()}
                disabled={p.cancelling}
              >
                <X className="ico ico-sm" aria-hidden />
                {p.cancelling ? t("files.cancelling") : t("common:actions.cancel")}
              </button>
            </div>
          </div>
        )}
        {items.map((f) => {
          const isFinal = f.kind === "render" && (f.quality ?? "").startsWith("final");
          const label =
            f.kind === "export" ? t("files.editableZip") : (qualityName(f.quality ?? "preview") ?? f.file);
          const name =
            f.kind === "export" ? `${p.title}-editable.zip` : `${p.title}-${f.quality ?? "video"}.mp4`;
          return (
            <div key={f.file} className="file">
              <span className={`fi ${isFinal ? "final" : ""}`}>
                {f.kind === "export" ? (
                  <Scissors className="ico" aria-hidden />
                ) : isFinal ? (
                  <Clapperboard className="ico" aria-hidden />
                ) : (
                  <Eye className="ico" aria-hidden />
                )}
              </span>
              <div>
                <div className="t">
                  {label}
                  {f.file === playing && <span className="badge">{t("files.playing")}</span>}
                </div>
                <div className="m">
                  {[
                    fmtWhen(f.created),
                    fmtSize(f.size),
                    f.kind === "export" ? "DaVinci, Premiere, Final Cut, Kdenlive" : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
              </div>
              <div className="a">
                {f.kind === "render" && f.file !== playing && (
                  <button
                    type="button"
                    className="icon-btn sm bare"
                    aria-label={t("files.play", { label })}
                    onClick={() => onPlay(f.file)}
                  >
                    <Play className="ico" />
                  </button>
                )}
                <a className="btn sm ghost" href={`/api/projects/${p.id}/files/${f.file}`} download={name}>
                  <Download className="ico ico-sm" aria-hidden />
                  <span className="dl-label">{t("common:actions.download")}</span>
                </a>
                <button
                  type="button"
                  className="icon-btn sm bare danger-text"
                  aria-label={t("files.deleteLabel", { label, when: fmtWhen(f.created, true) })}
                  onClick={() => void remove(f)}
                >
                  <Trash2 className="ico" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
      {confirmDialog}
    </section>
  );
}
