import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { api } from "@/api/client";
import { applyProject } from "@/api/queries";
import type { Project } from "@/api/types";
import { useToast } from "@/components/ui/Toast";
import i18n from "@/i18n";

/**
 * A toast for an edit with its own «Undo». With the edit's `edit_rev` (edit responses carry it, plan
 * replies too) the server undoes it only if nothing was changed after it; otherwise it says so instead of
 * undoing something else. The undo runs from the toast itself, not from the component that showed it (which
 * may be gone by then: another shot, a closed dialog), so a refusal is always reported.
 */
export function useUndoToast(pid: string) {
  const toast = useToast();
  const qc = useQueryClient();
  return useCallback(
    (text: string, result?: unknown) => {
      const rev =
        result && typeof result === "object" && "edit_rev" in result ? Number(result.edit_rev) : undefined;
      toast({
        text,
        action: {
          label: i18n.t("common:actions.undo"),
          run: () =>
            api
              .post<Project & { undone?: string }>(
                `/api/projects/${pid}/undo${rev != null ? `?expect_rev=${rev}` : ""}`,
              )
              .then((r) => {
                applyProject(qc, pid, r);
                toast({ text: i18n.t("common:undone", { what: r.undone }) });
              })
              .catch((e: Error) => toast({ text: e.message, tone: "error" })),
        },
      });
    },
    [pid, qc, toast],
  );
}
