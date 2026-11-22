import { useTranslation } from "react-i18next";

import type { Level, SignalInfo } from "@/api/types";
import {
  learnedChange,
  levelLabel,
  LEVELS,
  pct,
  SIGNAL_GROUPS,
  signalGroupTitle,
  signalText,
} from "@/lib/signals";

/**
 * Every signal with its level (None … Much more), grouped. For every project (the «Learning» page, with what
 * learning made of each) or for one project, where «Normal» means «as in general».
 */
export function SignalLevels({
  signals,
  levels,
  onChange,
  general,
  applied,
  disabled,
}: {
  signals: SignalInfo[];
  levels: Record<string, Level>;
  onChange: (key: string, level: Level) => void;
  /** project mode: the general level, shown next to each signal when it is not «Normal» */
  general?: Record<string, Level>;
  /** whether the learned weights are in use (else they are only shown as what it would do) */
  applied?: boolean;
  disabled?: boolean;
}) {
  const { t } = useTranslation("learning");
  const byKey = new Map(signals.map((s) => [s.key, s]));
  return (
    <div className="sig-groups">
      {SIGNAL_GROUPS.map((g) => (
        <section key={g.id} className="sig-group" aria-label={signalGroupTitle(g.id)}>
          <h3>{signalGroupTitle(g.id)}</h3>
          {g.keys.map((k) => {
            const s = byKey.get(k);
            const txt = signalText(k);
            if (!s) return null;
            const lv = levels[k] ?? 0;
            const learned = general ? null : learnedChange(s.default, s.learned);
            const gen = general?.[k] ?? 0;
            return (
              <div key={k} className="sig">
                <div className="sig-text">
                  <div className="sig-name">{txt.name}</div>
                  <div className="sig-help">
                    {txt.help}
                    {learned != null && (
                      <span className={`sig-learned ${applied ? "" : "muted"}`}>
                        {" "}
                        {t(applied ? "signal.learned" : "signal.learnedUnapplied", { pct: pct(learned) })}
                      </span>
                    )}
                    {gen !== 0 && (
                      <span className="sig-learned">
                        {" "}
                        {t("signal.general", { level: levelLabel(gen).toLowerCase() })}
                      </span>
                    )}
                  </div>
                </div>
                <div className="seg sig-seg" role="group" aria-label={txt.name}>
                  {LEVELS.map((v) => (
                    <button
                      key={v}
                      type="button"
                      aria-pressed={lv === v}
                      disabled={disabled}
                      onClick={() => onChange(k, v)}
                    >
                      {v === 0 && general ? t("signal.asUsual") : levelLabel(v)}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}
