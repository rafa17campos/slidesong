import { ArrowLeft, Check, Lock, Redo2, Undo2 } from "lucide-react";
import { useLayoutEffect, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { Plan, Project } from "@/api/types";
import { blocksEdits } from "@/lib/jobs";
import type { Step } from "@/lib/steps";

import { JobBar } from "./JobBar";
import { StepTabs } from "./StepTabs";

/** Sticky project header: back · title · step tabs · undo/redo + the step's main action · job bar. */
export function ProjectHeader({
  project: p,
  plan,
  step,
  action,
  onUndo,
  onRedo,
  saving,
  canEdit = true,
  saveError,
  onRetry,
}: {
  project: Project;
  plan?: Plan;
  step: Step;
  action?: ReactNode;
  onUndo: () => void;
  onRedo: () => void;
  saving?: boolean;
  canEdit?: boolean;
  /** the last settings save failed (kept pending, retried with the next change) */
  saveError?: string | null;
  onRetry?: () => void;
}) {
  const { t } = useTranslation("project");
  const ref = useRef<HTMLElement>(null);
  // the storyboard bar and the side panel stick right below the header, whatever its height
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const set = () => document.documentElement.style.setProperty("--phead-h", `${el.offsetHeight}px`);
    set();
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const h = p.history;
  return (
    <header className="phead" ref={ref}>
      <div className="phead-main">
        <Link className="icon-btn bare back" to="/" aria-label={t("header.back")}>
          <ArrowLeft className="ico" />
        </Link>
        <div className="ptitle">
          <h1 className="truncate">{p.title}</h1>
          {p.frozen && (
            <span className="badge" title={t("frozen.badgeTitle")}>
              <Lock className="ico ico-sm" aria-hidden /> {t("frozen.badge")}
            </span>
          )}
          {saveError ? (
            <button
              type="button"
              className="saved danger-text"
              onClick={onRetry}
              title={saveError}
              style={{ background: "none", border: 0, padding: 0 }}
            >
              {t("header.notSaved")}
            </button>
          ) : (
            <span className="saved hide-mobile" aria-live="polite" hidden={!canEdit}>
              {saving ? (
                t("header.saving")
              ) : (
                <>
                  <Check className="ico ico-sm" aria-hidden /> {t("header.saved")}
                </>
              )}
            </span>
          )}
        </div>
        <StepTabs project={p} plan={plan} current={step} />
        <div className="phead-actions">
          {canEdit && (
            <>
              <button
                type="button"
                className="icon-btn bare"
                onClick={onUndo}
                disabled={!h?.undo || blocksEdits(p)}
                aria-label={h?.undo ? t("history.undo", { what: h.undo }) : t("history.nothingToUndo")}
                title={h?.undo ? t("history.undoTitle", { what: h.undo }) : t("history.nothingToUndo")}
              >
                <Undo2 className="ico" />
              </button>
              <button
                type="button"
                className="icon-btn bare hide-mobile"
                onClick={onRedo}
                disabled={!h?.redo || blocksEdits(p)}
                aria-label={h?.redo ? t("history.redo", { what: h.redo }) : t("history.nothingToRedo")}
                title={h?.redo ? t("history.redoTitle", { what: h.redo }) : t("history.nothingToRedo")}
              >
                <Redo2 className="ico" />
              </button>
            </>
          )}
          {action}
        </div>
      </div>
      <JobBar project={p} />
    </header>
  );
}
