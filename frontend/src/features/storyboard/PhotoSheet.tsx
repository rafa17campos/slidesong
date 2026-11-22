import { useQuery } from "@tanstack/react-query";
import { Copy, ExternalLink, Play, RotateCcw, ScanFace, Star } from "lucide-react";
import { useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { api, assetUrl } from "@/api/client";
import { useConfig } from "@/api/queries";
import type { Analysis, Plan, Project } from "@/api/types";
import { Dialog } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";
import { locale } from "@/i18n";
import { isQualityWarning } from "@/lib/names";
import { shotBySlot } from "@/lib/storyboard";

import { useShotActions } from "./actions";

export interface SheetTarget {
  id: string;
  slot: number | null;
}

const num = (x: number, d = 1) =>
  x.toLocaleString(locale(), { maximumFractionDigits: d, minimumFractionDigits: d });

/** «Photo details»: the whole photo with its faces, and everything the app knows about it. */
export function PhotoSheet({
  project: p,
  plan,
  target,
  onClose,
  readOnly = false,
}: {
  project: Project;
  plan?: Plan;
  target: SheetTarget | null;
  onClose: () => void;
  readOnly?: boolean;
}) {
  const { t } = useTranslation("storyboard");
  return (
    <Dialog
      open={!!target}
      onClose={onClose}
      className="photo-sheet"
      bodyClassName="fi-body"
      title={
        <h2>
          {t("sheet.title")}
          {target?.slot != null && (
            <span className="muted" style={{ fontWeight: 500, fontSize: 15 }}>
              {" "}
              {t("sheet.shot", { n: target.slot + 1 })}
            </span>
          )}
        </h2>
      }
    >
      {target && <SheetBody key={target.id} project={p} plan={plan} target={target} readOnly={readOnly} />}
    </Dialog>
  );
}

function SheetBody({
  project: p,
  plan,
  target,
  readOnly,
}: {
  project: Project;
  plan?: Plan;
  target: SheetTarget;
  readOnly: boolean;
}) {
  const { t } = useTranslation("storyboard");
  const { id, slot } = target;
  const { data: a, error } = useQuery({
    queryKey: ["analysis", p.id, id, slot],
    queryFn: ({ signal }) =>
      api.get<Analysis>(
        `/api/projects/${p.id}/assets/${id}/analysis${slot != null ? `?slot=${slot}` : ""}`,
        signal,
      ),
    staleTime: 5 * 60_000,
  });
  const { data: config } = useConfig();
  const toast = useToast();
  const [faces, setFaces] = useState(true);
  const meta = p.assets[id];
  const video = !!meta?.video;
  const inShot = slot != null && p.slots[slot]?.asset === id;
  const why = slot != null ? (p.slots[slot]?.why?.[id] ?? []) : [];
  const ref =
    slot != null
      ? t("sheet.refShot", { id, project: p.id, n: slot + 1 })
      : t("sheet.ref", { id, project: p.id });
  const size = a?.size ?? (meta ? [meta.w, meta.h] : null);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(ref);
      toast({ text: t("sheet.copied") });
    } catch {
      toast({ text: t("sheet.copyFailed"), tone: "error" });
    }
  };

  return (
    <>
      <div className="stage">
        <div className="view">
          {video ? (
            <VideoPart project={p} plan={plan} id={id} slot={inShot ? slot : null} readOnly={readOnly} />
          ) : (
            <div className="imgwrap">
              <img src={assetUrl(id, "preview")} alt="" />
              {faces &&
                a?.faces.map((f, k) => (
                  <div
                    key={k}
                    className="fbox"
                    style={{
                      left: `${f.box[0] * 100}%`,
                      top: `${f.box[1] * 100}%`,
                      width: `${(f.box[2] - f.box[0]) * 100}%`,
                      height: `${(f.box[3] - f.box[1]) * 100}%`,
                    }}
                  >
                    <span>{f.name ?? "?"}</span>
                  </div>
                ))}
            </div>
          )}
        </div>
        <div className="stage-bar">
          {!video && (
            <button type="button" className="btn sm" aria-pressed={faces} onClick={() => setFaces(!faces)}>
              <ScanFace className="ico ico-sm" aria-hidden /> {t("sheet.faces")}
            </button>
          )}
          {size && (
            <span className="tnum">
              {size[0]} × {size[1]} · {size[0] >= size[1] ? t("sheet.landscape") : t("sheet.portrait")}
              {video && meta?.duration ? ` · ${Math.round(meta.duration)} s` : ""}
            </span>
          )}
          <span className="spacer" />
          {config?.immich_web && (
            <a className="btn sm" href={`${config.immich_web}/photos/${id}`} target="_blank" rel="noreferrer">
              <ExternalLink className="ico ico-sm" aria-hidden /> {t("sheet.openImmich")}
            </a>
          )}
        </div>
      </div>

      <div className="side">
        {why.length > 0 && (
          <section>
            <h3>{t("sheet.whyHere")}</h3>
            <div className="why">
              {why.map((w) => (
                <span key={w} className={`chip sm ${isQualityWarning(w) ? "warn" : ""}`}>
                  {w}
                </span>
              ))}
            </div>
          </section>
        )}

        {error && <p className="danger-text">{t("sheet.analyzeFailed", { error: error.message })}</p>}
        {!a && !error && <p className="muted">{t("sheet.analyzing")}</p>}

        {a?.lyric_pct != null && (
          <section className="reading">
            <h3>{t("sheet.fit.title")}</h3>
            <q>{a.lyric}</q>
            {a.lyric_ai && (
              <p style={{ margin: "8px 0" }}>
                <Trans
                  t={t}
                  i18nKey={
                    a.lyric_ai.visual && a.lyric_ai.visual !== a.lyric_ai.english
                      ? a.lyric_ai.source === "local"
                        ? "sheet.fit.localVisual"
                        : "sheet.fit.claudeVisual"
                      : a.lyric_ai.source === "local"
                        ? "sheet.fit.local"
                        : "sheet.fit.claude"
                  }
                  values={{ english: a.lyric_ai.english, visual: a.lyric_ai.visual }}
                  components={{ i: <i />, b: <b /> }}
                />
              </p>
            )}
            <div className="row">
              <div className="meter grow">
                <i style={{ width: `${a.lyric_pct}%` }} />
              </div>
              <b className="tnum">{a.lyric_pct}</b> <span className="muted">{t("sheet.fit.outOf")}</span>
            </div>
            <p className="text-caption muted" style={{ margin: "6px 0 0" }}>
              {t("sheet.fit.better", { pct: a.lyric_pct })}
            </p>
          </section>
        )}

        {a && (
          <section>
            <h3>{t("sheet.data.title")}</h3>
            <dl className="data">
              <dt>{t("sheet.data.date")}</dt>
              <dd>
                {a.date
                  ? new Date(a.date).toLocaleString(locale(), { dateStyle: "long", timeStyle: "short" })
                  : "?"}
              </dd>
              <dt>{t("sheet.data.place")}</dt>
              <dd>{a.place.length ? a.place.join(", ") : t("sheet.data.noPlace")}</dd>
              {!!a.nearby?.length && (
                <>
                  <dt>{t("sheet.data.nearby")}</dt>
                  <dd className="muted">
                    {a.nearby.slice(0, 10).join(", ")}
                    <span className="credit">
                      {" "}
                      ·{" "}
                      <a href="https://www.geonames.org" target="_blank" rel="noreferrer">
                        GeoNames
                      </a>{" "}
                      (CC BY 4.0)
                    </span>
                  </dd>
                </>
              )}
              <dt>{t("sheet.data.people")}</dt>
              <dd>
                {a.faces.length
                  ? a.faces.map((f) => f.name ?? t("sheet.data.noName")).join(", ")
                  : t("sheet.data.noFaces")}
              </dd>
              {a.camera && (
                <>
                  <dt>{t("sheet.data.camera")}</dt>
                  <dd>{a.camera}</dd>
                </>
              )}
              <dt>{t("sheet.data.file")}</dt>
              <dd className="muted">
                {a.file}
                {a.favorite && (
                  <>
                    {" "}
                    · <Star className="ico ico-sm" aria-hidden /> {t("sheet.data.favorite")}
                  </>
                )}
              </dd>
            </dl>
          </section>
        )}

        {a && (
          <section>
            <h3>{t("sheet.gpu.title")}</h3>
            {a.scores ? (
              <>
                {a.scores.aesthetic != null && (
                  <>
                    <div className="row">
                      <b className="grow">{t("sheet.gpu.aesthetic")}</b>
                      <b className="tnum">{num(a.scores.aesthetic)}</b>{" "}
                      <span className="muted">{t("sheet.gpu.outOf")}</span>
                    </div>
                    <div className="meter" style={{ marginTop: 6 }}>
                      <i style={{ width: `${a.scores.aesthetic * 10}%` }} />
                    </div>
                    <p className="text-caption muted" style={{ margin: "6px 0 10px" }}>
                      {t("sheet.gpu.typical")}
                    </p>
                  </>
                )}
                {a.scores.faces.length ? (
                  a.scores.faces.map((f, k) => (
                    <div key={k} className="face card-sunken">
                      <b>{f.name ?? t("sheet.data.noName")}</b>
                      <div className="facts">
                        <span>😁 {Math.round((f.smile ?? 0) * 100)} %</span>
                        <span>
                          👁️ {(f.eyes_open ?? 1) < 0.25 ? t("sheet.gpu.eyesClosed") : t("sheet.gpu.eyesOpen")}
                        </span>
                        <span>{f.frontal ? t("sheet.gpu.frontal") : t("sheet.gpu.side")}</span>
                        <span
                          className={
                            f.focus == null
                              ? "muted"
                              : f.focus < 1.6
                                ? "danger-text"
                                : f.focus < 1.8
                                  ? "warn-text"
                                  : "ok-text"
                          }
                        >
                          {f.focus == null
                            ? t("sheet.gpu.focusSmall")
                            : f.focus < 1.6
                              ? t("sheet.gpu.blurry", { v: num(f.focus) })
                              : f.focus < 1.8
                                ? t("sheet.gpu.soft", { v: num(f.focus) })
                                : t("sheet.gpu.sharp", { v: num(f.focus) })}
                        </span>
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="muted text-small">{t("sheet.gpu.noFaces")}</p>
                )}
              </>
            ) : (
              <p className="muted text-small">{t("sheet.gpu.notYet")}</p>
            )}
          </section>
        )}

        {a?.ram_tags && (
          <section>
            <h3>{t("sheet.modelSees")}</h3>
            <div className="why">
              {a.ram_tags.map((t) => (
                <span key={t} className={`chip sm ${a.sensitive_tags?.includes(t) ? "warn" : ""}`}>
                  {t}
                </span>
              ))}
            </div>
          </section>
        )}

        {config?.assistant_refs && (
          <section>
            <h3>{t("sheet.ask.title")}</h3>
            <p className="text-small muted" style={{ margin: "0 0 8px" }}>
              {t("sheet.ask.hint")}
            </p>
            <div className="ref card-sunken">
              <code>{ref}</code>
              <button type="button" className="btn sm" onClick={copy}>
                <Copy className="ico ico-sm" aria-hidden /> {t("sheet.ask.copy")}
              </button>
            </div>
          </section>
        )}
      </div>
    </>
  );
}

/** A video asset: the player, and (when it is in the shot) the part used, which can be moved. */
function VideoPart({
  project: p,
  plan,
  id,
  slot,
  readOnly,
}: {
  project: Project;
  plan?: Plan;
  id: string;
  slot: number | null;
  readOnly: boolean;
}) {
  const { t: tr } = useTranslation("storyboard");
  const v = useRef<HTMLVideoElement>(null);
  const act = useShotActions(p.id);
  const toast = useToast();
  const [t, setT] = useState(0);
  const [loaded, setLoaded] = useState(0);
  const sh = slot != null ? shotBySlot(plan).get(slot) : undefined;
  const dur = p.assets[id]?.duration || loaded;
  const from = sh?.clip_start ?? 0;
  const to = sh?.clip_end ?? 0;
  const custom = slot != null && p.slots[slot]?.clip_start != null;
  const playPart = () => {
    const el = v.current;
    if (!el) return;
    el.currentTime = from;
    void el.play();
    const stop = () => {
      if (el.currentTime >= to) {
        el.pause();
        el.removeEventListener("timeupdate", stop);
      }
    };
    el.addEventListener("timeupdate", stop);
  };
  const setStart = (clip_start: number | null) =>
    slot != null &&
    act.slot.mutate(
      { i: slot, change: { action: "clip", clip_start } },
      { onError: (e) => toast({ text: e.message, tone: "error" }) },
    );
  return (
    <div style={{ width: "100%" }}>
      <div className="imgwrap" style={{ display: "block", textAlign: "center" }}>
        <video
          ref={v}
          src={`/api/assets/${id}/video`}
          controls
          playsInline
          onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setLoaded(e.currentTarget.duration)}
          style={{ margin: "0 auto" }}
        />
      </div>
      {sh && dur > 0 && (
        <div className="vid-ctl">
          <div className="vtrack" aria-hidden>
            <div
              className="used"
              style={{ left: `${(from / dur) * 100}%`, width: `${((to - from) / dur) * 100}%` }}
            />
            <div className="head" style={{ left: `${(t / dur) * 100}%` }} />
          </div>
          <div className="text-small" style={{ color: "var(--color-stage-muted)" }}>
            <Trans
              t={tr}
              i18nKey={custom ? "sheet.video.usedChosen" : "sheet.video.usedCenter"}
              values={{ from: num(from), to: num(to), len: num(to - from) }}
              components={{ b: <b style={{ color: "var(--color-stage-ink)" }} /> }}
            />
          </div>
          <div className="row wrap">
            <button type="button" className="btn sm" onClick={playPart}>
              <Play className="ico ico-sm" aria-hidden /> {tr("sheet.video.play")}
            </button>
            {!readOnly && (
              <button
                type="button"
                className="btn sm primary"
                onClick={() => setStart(Math.round(t * 10) / 10)}
              >
                {tr("sheet.video.startHere", { t: num(t) })}
              </button>
            )}
            {custom && !readOnly && (
              <button type="button" className="btn sm" onClick={() => setStart(null)}>
                <RotateCcw className="ico ico-sm" aria-hidden /> {tr("sheet.video.backToCenter")}
              </button>
            )}
          </div>
        </div>
      )}
      {!sh && slot == null && (
        <p className="text-small" style={{ color: "var(--color-stage-muted)", padding: 12 }}>
          {tr("sheet.video.note")}
        </p>
      )}
    </div>
  );
}
