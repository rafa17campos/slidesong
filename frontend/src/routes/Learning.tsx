import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Ban, Check, Clapperboard, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link } from "react-router";

import { api, assetUrl } from "@/api/client";
import { learningDetailKey, useLearningDetail, useLearningEvents } from "@/api/queries";
import type { LearningDetail, LearningEvent, LearningProject, Level } from "@/api/types";
import { AppFooter } from "@/components/AppFooter";
import { LanguageSwitch } from "@/components/LanguageSwitch";
import { useConfirm } from "@/components/ui/Confirm";
import { useToast } from "@/components/ui/Toast";
import { SignalLevels } from "@/features/learning/SignalLevels";
import i18n, { locale } from "@/i18n";
import { learnedSummary } from "@/lib/signals";

type SourceKey = keyof (typeof import("@/i18n/locales/en/learning.json"))["events"]["source"];

/** How a correction was made (the server's `source`), as the key of its text. */
const SOURCE: Record<string, SourceKey> = {
  alts: "alts",
  options: "options",
  all: "all",
  search: "search",
  burst: "burst",
  immich: "immich",
  exchange: "swap",
  swap: "swap",
  pinned: "pinned",
  fijada: "pinned", // older logs
  pin: "pinAsIs",
};

/** «from the alternatives»… or "" */
const sourceText = (source?: string | null) => {
  if (source === "final") return i18n.t("learning:events.source.final");
  const k = source ? SOURCE[source] : undefined;
  return k ? i18n.t(`learning:events.source.${k}`) : "";
};

/** «A, B and C» in the interface language. */
const list = (xs: string[]) => new Intl.ListFormat(locale(), { type: "conjunction" }).format(xs);
const day = (iso?: string) =>
  iso ? new Date(iso).toLocaleDateString(locale(), { day: "numeric", month: "long" }) : "";

/** «Smiles count more; Immich favorites count less» */
function summary({ more, less }: { more: string[]; less: string[] }) {
  const m = more.length ? i18n.t("learning:status.more", { count: more.length, names: list(more) }) : "";
  const l = less.length ? i18n.t("learning:status.less", { count: less.length, names: list(less) }) : "";
  return m && l ? i18n.t("learning:status.both", { more: m, less: l }) : m || l;
}

/**
 * «Learning»: what the app has learned from the corrections and how much each signal counts, with levels set
 * by hand for every project; the corrections themselves (to remove the wrong ones), and which projects teach.
 */
export function LearningPage() {
  const { t } = useTranslation(["learning", "common"]);
  const { data, error } = useLearningDetail();
  const qc = useQueryClient();
  const toast = useToast();
  const [ask, confirmDialog] = useConfirm();

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: learningDetailKey });
    void qc.invalidateQueries({ queryKey: ["learning"] });
    void qc.invalidateQueries({ queryKey: ["learning-events"] });
  };
  const fail = (e: unknown) => toast({ text: (e as Error).message, tone: "error" });

  const setLevel = async (key: string, level: Level) => {
    if (!data) return;
    const levels = Object.fromEntries(data.signals.map((s) => [s.key, s.key === key ? level : s.level]));
    // at once on screen; the answer is the stored state
    qc.setQueryData<LearningDetail>(learningDetailKey, {
      ...data,
      signals: data.signals.map((s) => (s.key === key ? { ...s, level } : s)),
    });
    try {
      qc.setQueryData(learningDetailKey, await api.put<LearningDetail>("/api/learning/levels", { levels }));
    } catch (e) {
      fail(e);
      refresh();
    }
  };
  const resetLevels = async () => {
    try {
      qc.setQueryData(
        learningDetailKey,
        await api.put<LearningDetail>("/api/learning/levels", { levels: {} }),
      );
      toast({ text: t("levelsCard.resetDone") });
    } catch (e) {
      fail(e);
    }
  };
  const relearn = async () => {
    try {
      await api.post("/api/learning/relearn");
      toast({ text: t("status.relearnToast") });
      setTimeout(refresh, 800);
    } catch (e) {
      fail(e);
    }
  };

  const resetAll = async () => {
    const n = data?.projects.reduce((a, p) => a + p.corrections + p.accepted, 0) ?? 0;
    if (
      !(await ask({
        title: t("resetAll.title"),
        body: t("resetAll.body", { count: n }),
        confirm: t("resetAll.confirm"),
        tone: "danger",
      }))
    )
      return;
    try {
      const r = await api.post<{ forgotten: number }>("/api/learning/reset", {});
      toast({ text: t("resetAll.done", { count: r.forgotten }) });
      refresh();
    } catch (e) {
      fail(e);
    }
  };

  const st = data?.status;
  const touched = data?.signals.some((s) => s.level !== 0);
  const sum = data ? learnedSummary(data.signals) : { more: [], less: [] };

  return (
    <div className="pg-home pg-learn">
      <header className="topbar">
        <Link className="brand" to="/">
          <span className="brand-mark">
            <Clapperboard className="ico" />
          </span>
          Slidesong
        </Link>
        <span className="spacer" />
        <LanguageSwitch />
        <Link className="btn ghost sm" to="/">
          <ArrowLeft className="ico ico-sm" aria-hidden /> {t("page.back")}
        </Link>
      </header>
      <main className="page learn-page">
        <div className="hero">
          <div className="grow">
            <div className="eyebrow">{t("page.eyebrow")}</div>
            <h1>{t("page.title")}</h1>
            <p>
              <Trans t={t} i18nKey="page.intro" components={{ b: <b /> }} />
            </p>
          </div>
        </div>
        {error && <p className="danger-text">{error.message}</p>}
        {!data && !error && <p className="muted">{t("common:loading")}</p>}
        {data && st && (
          <>
            <section className="card-default p-5 learn-status" aria-labelledby="l-status">
              <div className="grow">
                <h2 id="l-status">{t("status.title")}</h2>
                <p className="text-small" style={{ margin: "6px 0 0" }}>
                  {(st.corrections ?? 0) < 20 ? (
                    t("status.few", { count: st.corrections ?? 0 })
                  ) : st.acc_default != null && st.acc_learned != null ? (
                    <>
                      <Trans
                        t={t}
                        i18nKey="status.accuracy"
                        values={{
                          n: st.corrections,
                          learned: Math.round(st.acc_learned * 100),
                          def: Math.round(st.acc_default * 100),
                        }}
                        components={{ b: <b /> }}
                      />{" "}
                      {st.applied ? (
                        <b>{t("status.inUse")}</b>
                      ) : (
                        <Trans t={t} i18nKey="status.notInUse" components={{ b: <b /> }} />
                      )}
                    </>
                  ) : (
                    t("status.noData")
                  )}
                </p>
                {(sum.more.length > 0 || sum.less.length > 0) && (
                  <p className="text-small secondary" style={{ margin: "6px 0 0" }}>
                    {t(st.applied ? "status.changed" : "status.wouldChange", { what: summary(sum) })}
                  </p>
                )}
                {st.updated && (
                  <p className="text-caption muted" style={{ margin: "6px 0 0" }}>
                    {t("status.updated", { date: day(st.updated) })}
                  </p>
                )}
              </div>
              <div className="stack" style={{ gap: 8, flex: "none" }}>
                <button type="button" className="btn" onClick={() => void relearn()} disabled={st.running}>
                  <RefreshCw className={`ico ico-sm ${st.running ? "spin" : ""}`} aria-hidden />
                  {st.running ? t("status.learning") : t("status.relearn")}
                </button>
                <button
                  type="button"
                  className="btn ghost danger-text"
                  onClick={() => void resetAll()}
                  disabled={st.running || !st.events}
                >
                  <RotateCcw className="ico ico-sm" aria-hidden />
                  {t("status.startOver")}
                </button>
              </div>
            </section>

            <section className="card-default p-5" aria-labelledby="l-levels">
              <div className="card-head">
                <h2 id="l-levels">{t("levelsCard.title")}</h2>
                <span className="spacer" />
                {touched && (
                  <button type="button" className="btn sm ghost" onClick={() => void resetLevels()}>
                    {t("levelsCard.reset")}
                  </button>
                )}
              </div>
              <p className="text-small secondary" style={{ margin: "4px 0 16px" }}>
                {t("levelsCard.intro")}
              </p>
              <SignalLevels
                signals={data.signals}
                levels={Object.fromEntries(data.signals.map((s) => [s.key, s.level]))}
                onChange={(k, v) => void setLevel(k, v)}
                applied={st.applied}
              />
            </section>

            <Corrections projects={data.projects} onChanged={refresh} />

            <section className="card-default p-5" aria-labelledby="l-projects">
              <h2 id="l-projects">{t("projects.title")}</h2>
              <p className="text-small secondary" style={{ margin: "4px 0 12px" }}>
                {t("projects.intro")}
              </p>
              <ul className="learn-projects">
                {data.projects.map((p) => (
                  <ProjectRow key={p.id} p={p} ask={ask} onChanged={refresh} busy={!!st.running} />
                ))}
              </ul>
            </section>
          </>
        )}
      </main>
      <AppFooter />
      {confirmDialog}
    </div>
  );
}

function ProjectRow({
  p,
  ask,
  onChanged,
  busy,
}: {
  p: LearningProject;
  ask: ReturnType<typeof useConfirm>[0];
  onChanged: () => void;
  busy: boolean;
}) {
  const { t } = useTranslation("learning");
  const toast = useToast();
  const n = p.corrections + p.accepted;
  const teach = async (on: boolean) => {
    if (
      !on &&
      !(await ask({
        title: p.deleted ? t("projects.stop.titleDeleted") : t("projects.stop.title", { title: p.title }),
        body: t("projects.stop.body", { count: n }),
        confirm: p.deleted ? t("projects.forget") : t("projects.stop.confirm"),
        tone: "warning",
      }))
    )
      return;
    try {
      await api.post(`/api/learning/projects/${p.id}`, { on });
      toast({
        text: on ? t("projects.stop.teachesAgain", { title: p.title }) : t("projects.stop.forgotten"),
      });
      onChanged();
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  const restart = async () => {
    if (
      !(await ask({
        title: t("projects.restart.title", { title: p.title }),
        body: t("projects.restart.body", { count: n }),
        confirm: t("projects.startOver"),
        tone: "warning",
      }))
    )
      return;
    try {
      const r = await api.post<{ forgotten: number }>("/api/learning/reset", { project: p.id });
      toast({ text: t("projects.restart.done", { count: r.forgotten, title: p.title }) });
      onChanged();
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  return (
    <li>
      <div className="grow">
        <div className="strong">{p.deleted ? t("projects.deleted") : p.title}</div>
        <div className="text-caption muted">
          {p.teaches ? (
            <>
              {t("projects.corrections", { count: p.corrections })} ·{" "}
              {t("projects.accepted", { count: p.accepted })}
              {!p.learned && ` · ${t("projects.factory")}`}
              {Object.keys(p.tuning).length > 0 && ` · ${t("projects.ownSettings")}`}
            </>
          ) : (
            t("projects.notTeaching")
          )}
        </div>
      </div>
      {p.deleted ? (
        n > 0 && (
          <button type="button" className="btn sm ghost" onClick={() => void teach(false)}>
            {t("projects.forget")}
          </button>
        )
      ) : (
        <>
          {p.teaches && n > 0 && (
            <button type="button" className="btn sm ghost" onClick={() => void restart()} disabled={busy}>
              {t("projects.startOver")}
            </button>
          )}
          <label className="tog">
            <span className="text-small">{t("projects.learnsFrom")}</span>
            <button
              type="button"
              className="switch"
              role="switch"
              aria-checked={p.teaches}
              aria-label={t("projects.learnsFromLabel", { title: p.title })}
              onClick={() => void teach(!p.teaches)}
            />
          </label>
        </>
      )}
    </li>
  );
}

function Corrections({ projects, onChanged }: { projects: LearningProject[]; onChanged: () => void }) {
  const { t } = useTranslation(["learning", "common"]);
  const [project, setProject] = useState("");
  const [accepted, setAccepted] = useState(false);
  const q = useLearningEvents(project, accepted);
  const toast = useToast();
  const events = q.data?.pages.flatMap((p) => p.events) ?? [];
  const total = q.data?.pages[0]?.total ?? 0;
  const remove = async (e: LearningEvent) => {
    try {
      await api.del(`/api/learning/events?${new URLSearchParams({ ts: e.ts, project: e.project })}`);
      toast({ text: t("events.removed") });
      onChanged();
    } catch (err) {
      toast({ text: (err as Error).message, tone: "error" });
    }
  };
  const named = projects.filter((p) => p.corrections + p.accepted > 0);
  return (
    <section className="card-default p-5" aria-labelledby="l-events">
      <div className="card-head wrap">
        <h2 id="l-events">{t("events.title")}</h2>
        <span className="spacer" />
        <select
          className="select"
          aria-label={t("events.project")}
          value={project}
          onChange={(e) => setProject(e.target.value)}
          style={{ width: "auto" }}
        >
          <option value="">{t("events.allProjects")}</option>
          {named.map((p) => (
            <option key={p.id} value={p.id}>
              {p.deleted ? t("projects.deleted") : p.title}
            </option>
          ))}
        </select>
      </div>
      <p className="text-small secondary" style={{ margin: "4px 0 12px" }}>
        {t("events.intro")}
      </p>
      <label className="tog" style={{ marginBottom: 8 }}>
        <span>{t("events.showAccepted")}</span>
        <button
          type="button"
          className="switch"
          role="switch"
          aria-checked={accepted}
          onClick={() => setAccepted(!accepted)}
        />
      </label>
      {q.isPending && <p className="muted text-small">{t("common:loading")}</p>}
      {!q.isPending && !events.length && <p className="muted text-small">{t("events.none")}</p>}
      <ul className="learn-events">
        {events.map((e) => (
          <li key={`${e.project}-${e.ts}`}>
            <div className="ev-photos" aria-hidden>
              {e.old && <img src={assetUrl(e.old)} alt="" loading="lazy" className={e.new ? "was" : "out"} />}
              {e.old && e.new && <ArrowRight className="ico ico-sm muted" />}
              {e.new && <img src={assetUrl(e.new)} alt="" loading="lazy" />}
              {!e.new && <Ban className="ico ico-sm danger-text" />}
              {e.action === "accept" && <Check className="ico ico-sm muted" />}
            </div>
            <div className="grow" style={{ minWidth: 0 }}>
              {e.lyric && <q className="ev-lyric">{e.lyric}</q>}
              <div className="text-caption muted">
                {[
                  t(
                    e.action === "reject"
                      ? "events.action.reject"
                      : e.action === "accept"
                        ? "events.action.accept"
                        : "events.action.change",
                  ),
                  sourceText(e.source),
                ]
                  .filter(Boolean)
                  .join(" ")}{" "}
                · {e.title ?? t("events.deletedProject")} · {t("events.shot", { n: e.slot + 1 })} ·{" "}
                {day(e.ts)}
              </div>
            </div>
            <button
              type="button"
              className="icon-btn sm bare"
              aria-label={t("events.remove")}
              title={t("events.removeHint")}
              onClick={() => void remove(e)}
            >
              <Trash2 className="ico" />
            </button>
          </li>
        ))}
      </ul>
      {q.hasNextPage && (
        <button
          type="button"
          className="btn sm ghost"
          onClick={() => void q.fetchNextPage()}
          disabled={q.isFetchingNextPage}
        >
          {t("events.more", { n: total - events.length })}
        </button>
      )}
    </section>
  );
}
