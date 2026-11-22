import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Brain,
  Clapperboard,
  CopyPlus,
  HardDriveDownload,
  Lock,
  Music,
  Plus,
} from "lucide-react";
import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { api, assetUrl } from "@/api/client";
import { keys, useBackupInfo, useLearning, useProjects, useWorker } from "@/api/queries";
import type { ProjectSummary } from "@/api/types";
import { AppFooter } from "@/components/AppFooter";
import { LanguageSwitch } from "@/components/LanguageSwitch";
import { Dialog } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";
import { BackupDialog } from "@/features/backup/BackupDialog";
import i18n, { locale } from "@/i18n";
import { jobLabel } from "@/lib/jobs";
import { stepLabel } from "@/lib/steps";

const when = (d: string | null) => {
  if (!d) return "";
  const t = new Date(d);
  const mins = (Date.now() - t.getTime()) / 60_000;
  if (mins < 60) return i18n.t("home:card.minsAgo", { n: Math.max(1, Math.round(mins)) });
  if (mins < 60 * 20) return i18n.t("home:card.hoursAgo", { n: Math.round(mins / 60) });
  return t.toLocaleDateString(locale(), { day: "numeric", month: "short" });
};

/** Where a project is and what to do next, for its card. */
export function projectState(p: ProjectSummary): {
  badge: string;
  tone?: "ok" | "info";
  next: string;
  to: string;
} {
  const t = i18n.t;
  if (p.running)
    return {
      badge: t("home:state.running", { job: jobLabel(p.running), pct: Math.round((p.progress ?? 0) * 100) }),
      tone: "info",
      next: t("home:state.progress"),
      to: `/p/${p.id}`,
    };
  const step = (n: number, s: Parameters<typeof stepLabel>[0]) =>
    t("home:state.step", { n, step: stepLabel(s) });
  if (!p.song) return { badge: step(1, "song"), next: t("home:state.upload"), to: `/p/${p.id}/song` };
  if (!p.slots) return { badge: step(1, "song"), next: t("home:state.analyze"), to: `/p/${p.id}/song` };
  if (!p.photos) return { badge: step(2, "photos"), next: t("home:state.suggest"), to: `/p/${p.id}/photos` };
  if (p.finals)
    return {
      badge: t("home:state.finalReady"),
      tone: "ok",
      next: t("home:state.watch"),
      to: `/p/${p.id}/video`,
    };
  return { badge: step(3, "storyboard"), next: t("home:state.review"), to: `/p/${p.id}/storyboard` };
}

export function Home() {
  const { t } = useTranslation(["home", "common"]);
  const { data, isPending, error } = useProjects();
  const { data: worker } = useWorker();
  const { data: L } = useLearning();
  const [creating, setCreating] = useState(false);
  const [backingUp, setBackingUp] = useState(false);
  const { data: backup } = useBackupInfo();
  return (
    <div className="pg-home">
      <header className="topbar">
        <Link className="brand" to="/">
          <span className="brand-mark">
            <Clapperboard className="ico" />
          </span>
          Slidesong
        </Link>
        <span className="spacer" />
        <LanguageSwitch />
        {worker && (
          <span className={`worker ${worker.online ? "" : "off"}`} title={t("worker.title")}>
            <span className={`dot ${!worker.online ? "off" : worker.busy ? "warn" : "ok"}`} />
            <span>{worker.name}</span>
            {/* phones: a word, not only the dot's colour */}
            <span className="wshort muted">
              ·{" "}
              {t(
                !worker.online
                  ? "worker.short.off"
                  : worker.busy
                    ? "worker.short.busy"
                    : "worker.short.ready",
              )}
            </span>
            <span className="wtext muted">
              ·{" "}
              {t(!worker.online ? "worker.long.off" : worker.busy ? "worker.long.busy" : "worker.long.ready")}
            </span>
          </span>
        )}
      </header>
      <main className="page">
        <div className="hero">
          <div className="grow">
            <div className="eyebrow">{t("hero.eyebrow")}</div>
            <h1>{t("hero.title")}</h1>
            <p>{t("hero.lead")}</p>
          </div>
          <button type="button" className="btn primary touch" onClick={() => setCreating(true)}>
            <Plus className="ico" aria-hidden /> {t("newVideo")}
          </button>
        </div>
        {isPending && <p className="muted">{t("common:loading")}</p>}
        {error && <p className="danger-text">{error.message}</p>}
        <div className="grid">
          {data && grouped(data).map(({ p, of }) => <ProjectCard key={p.id} p={p} of={of} />)}
          <button type="button" className="newcard" onClick={() => setCreating(true)}>
            <span className="in">
              <span className="plus">
                <Plus className="ico" aria-hidden />
              </span>
              {t("newVideo")}
            </span>
          </button>
        </div>
        {L && (
          <section className="card-sunken p-4 learn" aria-label={t("learning.label")}>
            <span className="li">
              <Brain className="ico" aria-hidden />
            </span>
            <div className="grow text-small">
              <b>{t("learning.heading")}</b>{" "}
              {t("learning.counts", {
                corrections: t("learning.corrections", { count: L.corrections ?? L.events ?? 0 }),
                preferences: t("learning.preferences", { count: L.pairs ?? 0 }),
              })}{" "}
              {L.acc_default != null && L.acc_learned != null ? (
                <>
                  <Trans
                    t={t}
                    i18nKey="learning.accuracy"
                    values={{ from: Math.round(L.acc_default * 100), to: Math.round(L.acc_learned * 100) }}
                    components={{
                      acc: <span className="acc" />,
                      arrow: <ArrowRight className="ico ico-sm" aria-hidden />,
                    }}
                  />{" "}
                  <span className="muted">{t(L.applied ? "learning.applied" : "learning.notApplied")}</span>
                </>
              ) : (
                <span className="muted">{t("learning.notYet")}</span>
              )}
            </div>
            <Link className="btn sm" to="/learning">
              {t("learning.open")}
            </Link>
          </section>
        )}
        {data && data.length > 0 && (
          <section className="card-sunken p-4 learn" aria-label={t("backup.label")}>
            <span className="li">
              <HardDriveDownload className="ico" aria-hidden />
            </span>
            <div className="grow text-small">
              <b>{t("backup.heading")}</b>{" "}
              <span className="muted">
                {backup?.last
                  ? t("backup.last", {
                      date: new Date(backup.last.made).toLocaleDateString(locale(), {
                        day: "numeric",
                        month: "long",
                      }),
                    })
                  : t("backup.never")}
              </span>
            </div>
            <button type="button" className="btn sm" onClick={() => setBackingUp(true)}>
              {t("backup.make")}
            </button>
          </section>
        )}
      </main>
      <AppFooter />
      <NewProject open={creating} onClose={() => setCreating(false)} />
      <BackupDialog open={backingUp} onClose={() => setBackingUp(false)} />
    </div>
  );
}

/** Versions right after the project they come from (the most recent first), so they do not mix. */
export function grouped(list: ProjectSummary[]): { p: ProjectSummary; of: ProjectSummary | null }[] {
  const byId = new Map(list.map((x) => [x.id, x]));
  const roots = list.filter((x) => !x.parent || !byId.has(x.parent));
  const out: { p: ProjectSummary; of: ProjectSummary | null }[] = [];
  const add = (x: ProjectSummary, of: ProjectSummary | null) => {
    out.push({ p: x, of });
    for (const child of list.filter((y) => y.parent === x.id)) add(child, x);
  };
  roots.forEach((r) => add(r, null));
  return out;
}

function ProjectCard({ p, of }: { p: ProjectSummary; of: ProjectSummary | null }) {
  const { t } = useTranslation("home");
  const st = projectState(p);
  return (
    <Link className="card-default pcard" to={st.to}>
      <div
        className="cover photo frame-169"
        style={
          p.cover
            ? { backgroundImage: `url(${assetUrl(p.cover)})` }
            : { display: "grid", placeItems: "center", background: "var(--color-sunken)" }
        }
      >
        {!p.cover && <Music className="ico ico-lg muted" aria-hidden />}
        <span className="st">
          <span className={`badge ${st.tone ?? ""}`}>{st.badge}</span>
          {p.frozen && (
            <span className="badge" style={{ marginLeft: 6 }} title={t("card.lockedHint")}>
              <Lock className="ico ico-sm" aria-hidden /> {t("card.locked")}
            </span>
          )}
        </span>
        {p.running && (
          <span className="prog">
            <i style={{ width: `${Math.round((p.progress ?? 0) * 100)}%` }} />
          </span>
        )}
      </div>
      <div className="body">
        <h2>{p.title}</h2>
        {of && (
          <div className="meta">
            <CopyPlus className="ico ico-sm" aria-hidden /> {t("card.versionOf", { title: of.title })}
          </div>
        )}
        <div className="meta">
          {p.song ? <span>{t("card.shots", { count: p.slots })}</span> : <span>{t("card.noSong")}</span>}·
          <span>{p.renders ? t("card.videos", { count: p.renders }) : t("card.noVideos")}</span>·
          <span>{when(p.updated)}</span>
        </div>
        <div className="next">
          {st.next} <ArrowRight className="ico ico-sm" aria-hidden />
        </div>
      </div>
    </Link>
  );
}

function NewProject({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation(["home", "common"]);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const create = async () => {
    if (!title.trim()) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("title", title.trim());
      const r = await api.post<{ id: string }>("/api/projects", fd);
      void qc.invalidateQueries({ queryKey: keys.projects });
      onClose();
      setTitle("");
      navigate(`/p/${r.id}/song`);
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} title={t("newVideo")}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          void create();
        }}
      >
        <label className="field">
          <span className="label">{t("create.title")}</span>
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t("create.placeholder")}
            maxLength={120}
            data-autofocus=""
            required
          />
          <span className="hint">{t("create.hint")}</span>
        </label>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn ghost" onClick={onClose}>
            {t("common:actions.cancel")}
          </button>
          <button type="submit" className="btn primary" disabled={busy || !title.trim()}>
            {t("create.submit")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
