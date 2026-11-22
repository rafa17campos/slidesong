import { useTranslation } from "react-i18next";

import type { Project } from "@/api/types";
import { energy, SECTION_COLOR, sectionName } from "@/lib/names";
import { fmtTime, type Group } from "@/lib/storyboard";

/** The song as coloured sections (height = energy), a tick per shot, amber dots on warnings, the open shot. */
export function SongMap({
  project: p,
  groups,
  warned,
  current,
  onSection,
}: {
  project: Project;
  groups: Group[];
  warned: number[];
  current: number | null;
  onSection: (g: number) => void;
}) {
  const { t } = useTranslation("storyboard");
  const total = p.song?.duration || p.slots.at(-1)?.end || 1;
  const pct = (t: number) => `${(t / total) * 100}%`;
  const cur = current != null ? p.slots[current] : null;
  return (
    <>
      <div className="songmap" role="group" aria-label={t("songMap.label")}>
        {groups.map((g, k) => {
          const sec = g.section;
          const c = SECTION_COLOR[sec?.kind ?? "verse"] ?? "var(--color-sec-verse)";
          const mood = sec?.mood ?? "mid";
          return (
            <button
              key={k}
              type="button"
              className="seg-s"
              style={{
                flex: g.to - g.from,
                ["--c" as string]: c,
                borderRadius: 6,
                padding: 0,
                cursor: "pointer",
              }}
              aria-label={`${sectionName(sec)}, ${fmtTime(g.from)}, ${energy(mood)}`}
              onClick={() => onSection(k)}
            >
              <span className="fill" style={{ height: `${{ low: 35, mid: 60, high: 92 }[mood] ?? 60}%` }} />
              <span className="lbl">{sectionName(sec)}</span>
            </button>
          );
        })}
        <div className="ticks">
          {p.slots.map((s, i) => (
            <i key={i} style={{ left: pct(s.start) }} />
          ))}
        </div>
        {warned.map((i) => {
          const s = p.slots[i]!;
          return (
            <span
              key={`w${i}`}
              className="ph-mark warn"
              style={{
                left: `calc(${pct((s.start + s.end) / 2)} - 3px)`,
                top: "auto",
                bottom: -6,
                height: 6,
                width: 6,
                borderRadius: "50%",
                boxShadow: "none",
              }}
              title={t("songMap.warning", { n: i + 1 })}
            />
          );
        })}
        {cur && (
          <span className="ph-mark" style={{ left: `calc(${pct((cur.start + cur.end) / 2)} - 1px)` }} />
        )}
      </div>
      <div className="songmap-legend hide-mobile">
        {[0, 60, 120, 180, 240, 300]
          .filter((t) => t < total - 15)
          .map((t) => (
            <span key={t}>{fmtTime(t)}</span>
          ))}
        <span>{fmtTime(total)}</span>
      </div>
    </>
  );
}
