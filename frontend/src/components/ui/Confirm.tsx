import { useCallback, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Dialog } from "./Dialog";

interface Ask {
  title: string;
  body?: ReactNode;
  confirm: string;
  tone?: "primary" | "danger" | "warning";
}

/** `const [ask, dialog] = useConfirm()`; `if (!(await ask({...}))) return;` and render `{dialog}`. */
export function useConfirm(): [(a: Ask) => Promise<boolean>, ReactNode] {
  const { t } = useTranslation();
  const [cur, setCur] = useState<Ask | null>(null);
  const resolve = useRef<(v: boolean) => void>(() => {});
  const ask = useCallback(
    (a: Ask) =>
      new Promise<boolean>((res) => {
        resolve.current = res;
        setCur(a);
      }),
    [],
  );
  const done = (v: boolean) => {
    resolve.current(v);
    setCur(null);
  };
  const dialog = (
    <Dialog open={!!cur} onClose={() => done(false)} title={cur?.title ?? ""}>
      {cur?.body && (
        <div className="text-small secondary" style={{ marginBottom: 16 }}>
          {cur.body}
        </div>
      )}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="btn ghost" onClick={() => done(false)}>
          {t("actions.cancel")}
        </button>
        <button
          type="button"
          className={`btn ${cur?.tone ?? "primary"}`}
          onClick={() => done(true)}
          data-autofocus=""
        >
          {cur?.confirm}
        </button>
      </div>
    </Dialog>
  );
  return [ask, dialog];
}
