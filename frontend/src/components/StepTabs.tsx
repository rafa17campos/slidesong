import { Check, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { Plan, Project } from "@/api/types";
import i18n from "@/i18n";
import { fmtTime, slotsWithWarnings } from "@/lib/storyboard";
import { STEPS, stepLabel, stepState, type Step } from "@/lib/steps";

function meta(p: Project, step: Step): string {
  switch (step) {
    case "song":
      return p.song?.duration ? fmtTime(p.song.duration) : "";
    case "photos": {
      const n = p.slots.filter((s) => s.asset).length;
      return p.slots.length ? `${n}/${p.slots.length}` : "";
    }
    case "storyboard":
      return p.slots.length ? i18n.t("project:tabs.shots", { count: p.slots.length }) : "";
    case "video":
      return p.renders.length ? i18n.t("project:tabs.videos", { count: p.renders.length }) : "";
  }
}

export function StepTabs({ project: p, plan, current }: { project: Project; plan?: Plan; current: Step }) {
  const { t } = useTranslation("project");
  const warnings = p.slots.length ? slotsWithWarnings(p, plan).length : 0;
  return (
    <nav className="steps" aria-label={t("tabs.label")}>
      {STEPS.map((s, k) => {
        const st = stepState(p, s);
        const warn = s === "storyboard" && warnings > 0;
        const label = [
          t("tabs.step", { n: k + 1, name: stepLabel(s) }),
          st === "done" && t("tabs.done"),
          warn && t("tabs.warnings", { count: warnings }),
          st === "working" && t("tabs.working"),
        ]
          .filter(Boolean)
          .join(", ");
        return (
          <Link
            key={s}
            to={`/p/${p.id}/${s}`}
            className="step"
            aria-current={s === current ? "page" : undefined}
            aria-label={label}
          >
            <span className={`n ${st === "done" ? "done" : ""} ${st === "working" ? "busy" : ""}`}>
              {st === "done" ? <Check className="ico ico-sm" aria-hidden /> : k + 1}
            </span>
            <span>{stepLabel(s)}</span>
            {warn ? (
              <span className="badge solid-warn" title={t("tabs.warnedShots")}>
                <TriangleAlert className="ico ico-sm" aria-hidden />
                {warnings}
              </span>
            ) : (
              <span className="meta">{meta(p, s)}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
