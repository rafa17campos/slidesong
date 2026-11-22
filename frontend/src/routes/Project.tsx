import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Clapperboard,
  Copy,
  CopyPlus,
  Ellipsis,
  HardDriveDownload,
  Lock,
  LockOpen,
  Play,
  Redo2,
  Sparkles,
  Trash2,
  Undo2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import {
  useConfig,
  applyProject,
  coverageKey,
  fetchCoverage,
  keys,
  useHistoryStep,
  usePlan,
  useProject,
  useStartJob,
} from "@/api/queries";
import type { Coverage, JobKind, Project } from "@/api/types";
import { ProjectHeader } from "@/components/ProjectHeader";
import { useConfirm } from "@/components/ui/Confirm";
import { useToast } from "@/components/ui/Toast";
import { StoryboardStep } from "@/features/storyboard/StoryboardStep";
import { SongStep } from "@/features/project/SongStep";
import { Ctx, type ProjectCtx } from "@/features/project/context";
import { PhotosStep } from "@/features/project/PhotosStep";
import { BackupDialog } from "@/features/backup/BackupDialog";
import { NewVersion } from "@/features/project/NewVersion";
import { VideoStep } from "@/features/project/VideoStep";
import { useSettings } from "@/hooks/useSettings";
import { useShortcuts } from "@/hooks/useShortcuts";
import { locale } from "@/i18n";
import { blocksEdits, jobLabel } from "@/lib/jobs";
import { initialStep, isStep, lastStep, legacyStepUrl, rememberStep } from "@/lib/steps";

export function ProjectRedirect() {
  const { pid = "" } = useParams();
  const { data, error } = useProject(pid);
  const { t } = useTranslation(["project", "common"]);
  if (error && !data) return <p className="page danger-text">{error.message}</p>;
  if (!data) return <p className="page muted">{t("common:loading")}</p>;
  return <Navigate to={`/p/${pid}/${initialStep(data, lastStep(pid))}`} replace />;
}

export function ProjectPage() {
  const { pid = "", step } = useParams();
  const { t } = useTranslation(["project", "common"]);
  const { data: p, error, refetch } = useProject(pid);
  const hasShots = !!p?.slots.some((s) => s.asset);
  const { data: plan } = usePlan(pid, hasShots);
  const { data: config } = useConfig();
  const history = useHistoryStep(pid);
  const start = useStartJob(pid);
  const settings = useSettings(pid);
  const toast = useToast();
  const [ask, confirmDialog] = useConfirm();
  const navigate = useNavigate();
  const qc = useQueryClient();

  useEffect(() => {
    if (isStep(step)) rememberStep(pid, step);
  }, [pid, step]);

  // a long job just ended: say so, with a way to see the result
  const running = p?.running ?? null;
  const wasRunning = useRef<string | null>(running);
  useEffect(() => {
    const was = wasRunning.current;
    wasRunning.current = running;
    if (!was || running || !p) return;
    const job = p.jobs[was as JobKind];
    if (job?.state !== "done") return;
    const go = (to: string, label: string) => ({ label, run: () => navigate(`/p/${pid}/${to}`) });
    const done: Record<string, [string, ReturnType<typeof go> | undefined]> = {
      render: [t("done.render"), step === "video" ? undefined : go("video", t("done.see"))],
      export: [t("done.export"), step === "video" ? undefined : go("video", t("done.see"))],
      suggest: [t("done.suggest"), step === "storyboard" ? undefined : go("storyboard", t("done.review"))],
      analyze: [t("done.analyze"), step === "photos" ? undefined : go("photos", t("done.choosePhotos"))],
    };
    const [text, action] = done[was] ?? [];
    if (text) toast({ text, action });
  }, [running, p, pid, step, navigate, toast, t]);

  // a settings save that fails must not look saved
  const saveError = settings.error;
  useEffect(() => {
    if (saveError) toast({ text: t("saveFailed", { error: saveError }), tone: "error" });
  }, [saveError, toast, t]);

  const undoRedo = async (dir: "undo" | "redo"): Promise<void> => {
    // what was just typed is saved first, so undo takes back the latest change and not the one before it
    await settings.flush().catch(() => {});
    history.mutate(dir, {
      onSuccess: (r) =>
        toast({
          text:
            dir === "undo"
              ? t("history.undone", { what: r.undone })
              : t("history.redone", { what: r.redone }),
          action: {
            label: dir === "undo" ? t("common:actions.redo") : t("common:actions.undo"),
            run: () => void undoRedo(dir === "undo" ? "redo" : "undo"),
          },
        }),
      onError: (e) => toast({ text: e.message, tone: "error" }),
    });
  };
  // not on a blocked project, nor while a job that rewrites the shots runs (the server would refuse)
  useShortcuts(
    { "mod+z": () => void undoRedo("undo"), "mod+shift+z": () => void undoRedo("redo") },
    !!p && !p.frozen && !blocksEdits(p),
  );

  const [versionOpen, setVersionOpen] = useState(false);
  const [backupOpen, setBackupOpen] = useState(false);
  const [quality, setQuality] = useState<"final" | "final2k" | "final4k">("final");
  const ctx = useMemo<ProjectCtx | null>(() => {
    if (!p) return null;
    const run = async (kind: JobKind, query?: Record<string, string>) => {
      try {
        await settings.flush(); // what was just typed (title, text at the start…) must be in
        await start.mutateAsync({ kind, query });
      } catch (e) {
        toast({ text: (e as Error).message, tone: "error" });
      }
    };
    return {
      project: p,
      plan,
      settings,
      busy: !!p.running,
      frozen: !!p.frozen,
      readOnly: !!p.frozen || p.running === "analyze" || p.running === "suggest",
      quality,
      setQuality,
      newVersion: () => setVersionOpen(true),
      analyze: async () => {
        if (p.slots.some((s) => s.asset)) {
          const ok = await ask({
            title: t("analyze.confirm.title"),
            body: t("analyze.confirm.body"),
            confirm: t("analyze.confirm.confirm"),
            tone: "warning",
          });
          if (!ok) return;
        }
        await run("analyze");
      },
      suggest: async () => {
        if (!p.people?.length) {
          const ok = await ask({
            title: t("suggest.noPeople.title"),
            body: t("suggest.noPeople.body"),
            confirm: t("suggest.noPeople.confirm"),
          });
          if (!ok) return;
        }
        // without the GPU worker, photos not analysed yet carry no quality data and no sensitive-photo warning
        let cov: Coverage | null = null;
        if (!qc.getQueryData(coverageKey(p))) toast({ text: t("suggest.checking") });
        try {
          cov = await qc.fetchQuery({
            queryKey: coverageKey(p),
            queryFn: () => fetchCoverage(p.id),
            staleTime: 30_000,
          });
        } catch {
          /* not knowing is no reason to block the suggestion */
        }
        if (cov && cov.pending > 0 && !cov.can_analyse) {
          const ok = await ask({
            title: t("suggest.noGpu.title", { name: cov.name }),
            body: (
              <>
                <p style={{ margin: "0 0 8px" }}>
                  <Trans
                    t={t}
                    i18nKey="suggest.noGpu.pending"
                    count={cov.pending}
                    values={{
                      name: cov.name,
                      pending: cov.pending.toLocaleString(locale()),
                      pool: cov.pool.toLocaleString(locale()),
                    }}
                    components={{ b: <b /> }}
                  />
                </p>
                <p style={{ margin: 0 }}>
                  <Trans
                    t={t}
                    i18nKey="suggest.noGpu.risk"
                    values={{ name: cov.name }}
                    components={{ b: <b /> }}
                  />
                </p>
              </>
            ),
            confirm: t("suggest.noGpu.confirm"),
            tone: "warning",
          });
          if (!ok) return;
        }
        await run("suggest");
      },
      render: (quality) => run("render", { quality }),
      exportZip: () => run("export"),
    };
  }, [p, plan, settings, start, toast, ask, qc, quality, t]);

  if (!isStep(step))
    return <Navigate to={legacyStepUrl(pid, step, window.location.search) ?? `/p/${pid}`} replace />;
  // only when there is nothing to show: a failed background refresh must not wipe the page (dialogs, typing)
  if (error && !p) return <p className="page danger-text">{error.message}</p>;
  if (!p || !ctx) return <p className="page muted">{t("common:loading")}</p>;

  const photos = p.slots.filter((s) => s.asset).length;
  const action = (() => {
    const dis = !!p.running || start.isPending;
    const waitMsg = p.running ? t("action.wait", { job: jobLabel(p.running) }) : t("action.moment");
    switch (step) {
      case "song":
        return p.slots.length || p.frozen ? (
          <button type="button" className="btn soft-primary" onClick={() => navigate(`/p/${pid}/photos`)}>
            <span className="hide-mobile">{t("action.nextPhotos")}</span>
            <span className="only-mobile">{t("common:steps.photos")}</span>
            <ArrowRight className="ico" aria-hidden />
          </button>
        ) : p.song ? (
          <button
            type="button"
            className="btn primary"
            disabled={dis}
            title={dis ? waitMsg : undefined}
            onClick={() => void ctx.analyze()}
          >
            <Sparkles className="ico" aria-hidden />
            <span className="hide-mobile">{t("action.analyze")}</span>
            <span className="only-mobile">{t("action.analyzeShort")}</span>
          </button>
        ) : null;
      case "photos":
        return p.slots.length && !p.frozen ? (
          <button
            type="button"
            className="btn primary"
            disabled={dis}
            title={dis ? waitMsg : undefined}
            onClick={() => void ctx.suggest()}
          >
            <Sparkles className="ico" aria-hidden />
            <span className="hide-mobile">{photos ? t("action.suggestAgain") : t("action.suggest")}</span>
            <span className="only-mobile">{t("action.suggestShort")}</span>
          </button>
        ) : null;
      case "storyboard":
        return photos ? (
          <button
            type="button"
            className="btn primary"
            disabled={dis}
            title={dis ? waitMsg : undefined}
            onClick={() => void ctx.render("preview")}
          >
            <Play className="ico" aria-hidden />
            <span className="hide-mobile">{t("action.preview")}</span>
            <span className="only-mobile">{t("action.previewShort")}</span>
          </button>
        ) : null;
      case "video":
        return photos ? (
          <button
            type="button"
            className="btn primary"
            disabled={dis}
            title={dis ? waitMsg : undefined}
            onClick={() => void ctx.render(quality)}
          >
            <Clapperboard className="ico" aria-hidden />
            <span className="hide-mobile">{t("action.final")}</span>
            <span className="only-mobile">{t("action.finalShort")}</span>
          </button>
        ) : null;
    }
  })();

  const freeze = async (on: boolean) => {
    const ok = await ask(
      on
        ? {
            title: t("freeze.confirm.title"),
            body: t("freeze.confirm.body"),
            confirm: t("freeze.confirm.confirm"),
          }
        : {
            title: t("unfreeze.confirm.title"),
            body: t("unfreeze.confirm.body"),
            confirm: t("unfreeze.confirm.confirm"),
            tone: "warning",
          },
    );
    if (!ok) return;
    try {
      const r = await api.post<Project>(`/api/projects/${pid}/freeze`, { on });
      applyProject(qc, pid, r, { plan: false });
      void qc.invalidateQueries({ queryKey: keys.projects });
      toast({ text: on ? t("freeze.done") : t("unfreeze.done") });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };

  const remove = async () => {
    const ok = await ask({
      title: t("delete.confirm.title", { title: p.title }),
      body: t("delete.confirm.body"),
      confirm: t("delete.confirm.confirm"),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/api/projects/${pid}`);
      void qc.invalidateQueries({ queryKey: keys.projects });
      navigate("/");
      toast({ text: t("delete.done", { title: p.title }) });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };

  return (
    <Ctx.Provider value={ctx}>
      <div className="min-h-dvh">
        <ProjectHeader
          project={p}
          plan={plan}
          step={step}
          saving={settings.saving}
          saveError={settings.error}
          onRetry={() => void settings.flush().catch(() => {})}
          action={
            <>
              {action}
              <ProjectMenu
                assistantRefs={!!config?.assistant_refs}
                onCopy={async () => {
                  try {
                    await navigator.clipboard.writeText(t("copy.ref", { id: p.id }));
                    toast({ text: t("copy.done") });
                  } catch {
                    toast({ text: t("copy.failed", { id: p.id }), tone: "error" });
                  }
                }}
                onDelete={() => void remove()}
                onVersion={() => setVersionOpen(true)}
                onBackup={() => setBackupOpen(true)}
                undo={!p.frozen && !blocksEdits(p) ? (p.history?.undo ?? null) : null}
                redo={!p.frozen && !blocksEdits(p) ? (p.history?.redo ?? null) : null}
                onUndo={() => void undoRedo("undo")}
                onRedo={() => void undoRedo("redo")}
                onFreeze={() => void freeze(!p.frozen)}
                frozen={!!p.frozen}
                disabled={!!p.running}
              />
            </>
          }
          onUndo={() => void undoRedo("undo")}
          onRedo={() => void undoRedo("redo")}
          canEdit={!p.frozen}
        />
        {error && (
          <div className="frozen-bar danger-text" role="alert">
            <span className="grow">{t("stale", { error: error.message })}</span>
            <button type="button" className="btn sm" onClick={() => void refetch()}>
              {t("common:actions.retry")}
            </button>
          </div>
        )}
        {p.frozen && (
          <div className="frozen-bar" role="status">
            <Lock className="ico" aria-hidden />
            <span className="grow">
              <Trans
                t={t}
                i18nKey="frozen.bar"
                values={{
                  date: new Date(p.frozen.at).toLocaleDateString(locale(), { day: "numeric", month: "long" }),
                }}
                components={{ b: <b /> }}
              />
            </span>
            <button type="button" className="btn sm soft-primary" onClick={() => setVersionOpen(true)}>
              <CopyPlus className="ico ico-sm" aria-hidden />
              <span className="hide-mobile">{t("frozen.newVersion")}</span>
              <span className="only-mobile">{t("frozen.newVersionShort")}</span>
            </button>
            <button
              type="button"
              className="btn sm ghost hide-mobile"
              onClick={() => void freeze(false)}
              disabled={!!p.running}
            >
              <LockOpen className="ico ico-sm" aria-hidden />
              {t("frozen.unlock")}
            </button>
          </div>
        )}
        {p.parent && (
          <div className="version-of muted text-small">
            <Trans
              t={t}
              i18nKey="versionOf"
              values={{ title: p.parent.title }}
              components={{ link: <Link to={`/p/${p.parent.id}`} /> }}
            />
          </div>
        )}
        {step === "storyboard" && <StoryboardStep project={p} plan={plan} readOnly={ctx.readOnly} />}
        {step === "song" && <SongStep />}
        {step === "photos" && <PhotosStep />}
        {step === "video" && <VideoStep />}
        {confirmDialog}
        <NewVersion project={p} open={versionOpen} onClose={() => setVersionOpen(false)} />
        <BackupDialog project={p} open={backupOpen} onClose={() => setBackupOpen(false)} />
      </div>
    </Ctx.Provider>
  );
}

function ProjectMenu({
  onCopy,
  assistantRefs,
  onDelete,
  onVersion,
  onBackup,
  undo,
  redo,
  onUndo,
  onRedo,
  onFreeze,
  frozen,
  disabled,
}: {
  onCopy: () => void;
  /** «Copy reference for Claude» is on (SLIDESONG_ASSISTANT_REFERENCES) */
  assistantRefs: boolean;
  onDelete: () => void;
  onVersion: () => void;
  onBackup: () => void;
  undo: string | null;
  redo: string | null;
  onUndo: () => void;
  onRedo: () => void;
  onFreeze: () => void;
  frozen: boolean;
  disabled: boolean;
}) {
  const { t } = useTranslation(["project", "common"]);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  const item = (fn: () => void) => () => {
    setOpen(false);
    fn();
  };
  return (
    <div ref={box} style={{ position: "relative" }}>
      <button
        type="button"
        className="icon-btn bare"
        aria-label={t("menu.label")}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Ellipsis className="ico" />
      </button>
      {open && (
        <div
          className="popover menu"
          style={{ position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 40 }}
        >
          <button type="button" onClick={item(onUndo)} disabled={!undo}>
            <Undo2 className="ico" /> {undo ? t("history.undo", { what: undo }) : t("history.nothingToUndo")}
          </button>
          <button type="button" onClick={item(onRedo)} disabled={!redo}>
            <Redo2 className="ico" /> {redo ? t("history.redo", { what: redo }) : t("history.nothingToRedo")}
          </button>
          <hr />
          <button type="button" onClick={item(onVersion)}>
            <CopyPlus className="ico" /> {t("menu.newVersion")}
          </button>
          <button type="button" onClick={item(onFreeze)} disabled={disabled}>
            {frozen ? <LockOpen className="ico" /> : <Lock className="ico" />}{" "}
            {frozen ? t("menu.unlock") : t("menu.lock")}
          </button>
          <hr />
          <button type="button" onClick={item(onBackup)}>
            <HardDriveDownload className="ico" /> {t("menu.backup")}
          </button>
          {assistantRefs && (
            <button type="button" onClick={item(onCopy)}>
              <Copy className="ico" /> {t("menu.copyRef")}
            </button>
          )}
          <hr />
          <button
            type="button"

            className="danger-text"
            onClick={item(onDelete)}
            disabled={disabled || frozen}
            title={frozen ? t("menu.unlockToDelete") : undefined}
          >
            <Trash2 className="ico" /> {t("menu.delete")}
          </button>
        </div>
      )}
    </div>
  );
}
