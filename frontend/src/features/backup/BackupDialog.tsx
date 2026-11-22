import { useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { backupInfoKey, useBackupInfo } from "@/api/queries";
import type { Project } from "@/api/types";
import { Dialog } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";
import { locale } from "@/i18n";
import { fmtSize } from "@/lib/format";

/**
 * «Backup»: a zip of everything (from the home page) or of one project (its ⋯ menu), laid out like
 * the data folder, so restoring is unzipping it there. The videos made are optional: they weigh the most and
 * can be made again.
 */
export function BackupDialog({
  open,
  onClose,
  project,
}: {
  open: boolean;
  onClose: () => void;
  project?: Project;
}) {
  const { t } = useTranslation("backup");
  return (
    <Dialog open={open} onClose={onClose} title={project ? t("titleProject") : t("title")}>
      {open && <Body project={project} onClose={onClose} />}
    </Dialog>
  );
}

function Body({ project: p, onClose }: { project?: Project; onClose: () => void }) {
  const { t } = useTranslation(["backup", "common"]);
  const { data: info } = useBackupInfo(!p);
  const [videos, setVideos] = useState(false);
  const toast = useToast();
  const qc = useQueryClient();
  const videosSize = p ? p.renders.reduce((n, r) => n + (r.size ?? 0), 0) : info?.videos_size;
  const hasVideos = p ? p.renders.length > 0 : !!info?.videos_size;
  const q = new URLSearchParams();
  if (videos) q.set("videos", "true");
  if (p) q.set("project", p.id);
  const href = `/api/backup${q.size ? `?${q}` : ""}`;
  return (
    <div className="stack">
      <p className="text-small secondary" style={{ margin: 0 }}>
        {p ? t("aboutProject", { title: p.title }) : t("aboutAll")}
      </p>
      {!p && info && (
        <p className="text-small muted" style={{ margin: 0 }}>
          {t("projects", { count: info.projects })} · ≈ {fmtSize(info.size)} ·{" "}
          {info.last
            ? t("last", {
                date: new Date(info.last.made).toLocaleDateString(locale(), {
                  day: "numeric",
                  month: "long",
                }),
              })
            : t("never")}
        </p>
      )}
      {hasVideos && (
        <label className="tog">
          <span>
            {t("includeVideos")}
            {videosSize ? <span className="muted"> (+{fmtSize(videosSize)})</span> : null}
          </span>
          <button
            type="button"
            className="switch"
            role="switch"
            aria-checked={videos}
            onClick={() => setVideos(!videos)}
          />
        </label>
      )}
      <p className="text-caption muted" style={{ margin: 0 }}>
        <Trans t={t} i18nKey="restore" components={{ code: <code /> }} />
      </p>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="btn ghost" onClick={onClose}>
          {t("common:actions.cancel")}
        </button>
        <a
          className="btn primary"
          href={href}
          download
          data-autofocus=""
          onClick={() => {
            toast({ text: t("preparing") });
            onClose();
            setTimeout(() => void qc.invalidateQueries({ queryKey: backupInfoKey }), 15_000);
          }}
        >
          <Download className="ico" aria-hidden />
          {t("common:actions.download")}
        </a>
      </div>
    </div>
  );
}
