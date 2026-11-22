import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { api } from "@/api/client";
import { keys, useProjects } from "@/api/queries";
import type { Project } from "@/api/types";
import { Dialog } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";

/** «Create a new version»: a copy of the whole edit (not its videos), to go on from there. */
export function NewVersion({
  project: p,
  open,
  onClose,
}: {
  project: Project;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation(["project", "common"]);
  const { data: all } = useProjects();
  const root = p.parent?.id ?? p.id;
  const n = (all ?? []).filter((x) => x.id === root || x.parent === root).length;
  const base = p.parent?.title ?? p.title;
  return (
    <Dialog open={open} onClose={onClose} title={t("newVersion.title")}>
      {open && (
        <Body key={p.id} project={p} suggested={`${base} · v${Math.max(2, n + 1)}`} onClose={onClose} />
      )}
    </Dialog>
  );
}

function Body({
  project: p,
  suggested,
  onClose,
}: {
  project: Project;
  suggested: string;
  onClose: () => void;
}) {
  const { t } = useTranslation(["project", "common"]);
  const [title, setTitle] = useState(suggested);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const create = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ id: string }>(`/api/projects/${p.id}/duplicate`, { title: title.trim() });
      void qc.invalidateQueries({ queryKey: keys.projects });
      onClose();
      navigate(`/p/${r.id}/storyboard`);
      toast({ text: t("newVersion.created", { title: p.title }) });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        void create();
      }}
    >
      <p className="text-small secondary" style={{ margin: 0 }}>
        {t("newVersion.body", { title: p.title })}
      </p>
      <label className="field">
        <span className="label">{t("newVersion.name")}</span>
        <input
          className="input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          data-autofocus=""
          required
          maxLength={120}
        />
      </label>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="btn ghost" onClick={onClose}>
          {t("common:actions.cancel")}
        </button>
        <button type="submit" className="btn primary" disabled={busy || !title.trim()}>
          {t("newVersion.create")}
        </button>
      </div>
    </form>
  );
}
