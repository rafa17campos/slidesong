import { Trans, useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useLearningDetail } from "@/api/queries";
import type { Level } from "@/api/types";
import { Dialog } from "@/components/ui/Dialog";

import { SignalLevels } from "./SignalLevels";

/** «Settings for this project»: levels on top of the general ones, for this project only. */
export function ProjectTuning({
  open,
  onClose,
  value,
  onChange,
  disabled,
}: {
  open: boolean;
  onClose: () => void;
  value: Record<string, Level>;
  onChange: (t: Record<string, Level>) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation(["learning", "common"]);
  const { data } = useLearningDetail();
  const n = Object.keys(value).length;
  return (
    <Dialog open={open} onClose={onClose} title={t("tuning.title")} wide>
      {open && (
        <div className="stack">
          <p className="text-small secondary" style={{ margin: 0 }}>
            <Trans t={t} i18nKey="tuning.intro" components={{ link: <Link to="/learning" /> }} />
          </p>
          {data ? (
            <SignalLevels
              signals={data.signals}
              levels={value}
              general={Object.fromEntries(data.signals.map((s) => [s.key, s.level]))}
              onChange={(k, v) => {
                const next = { ...value };
                if (v) next[k] = v;
                else delete next[k];
                onChange(next);
              }}
              disabled={disabled}
            />
          ) : (
            <p className="muted">{t("common:loading")}</p>
          )}
          <div className="row" style={{ justifyContent: "flex-end" }}>
            {n > 0 && (
              <button type="button" className="btn ghost" onClick={() => onChange({})} disabled={disabled}>
                {t("tuning.resetAll")}
              </button>
            )}
            <button type="button" className="btn primary" onClick={onClose} data-autofocus="">
              {t("common:actions.done")}
            </button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
