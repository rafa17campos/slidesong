import { Captions, Columns2, Film, Pin, Repeat2, TriangleAlert, ZoomIn } from "lucide-react";
import { memo } from "react";
import { useTranslation } from "react-i18next";

import type { Project, Shot } from "@/api/types";
import { fmtTime, type Warning } from "@/lib/storyboard";

import { ShotFrame } from "./ShotFrame";

export const ShotTile = memo(function ShotTile({
  project: p,
  shot,
  i,
  warnings,
  current,
  xsrc,
  onPick,
}: {
  project: Project;
  shot: Shot | undefined;
  i: number;
  warnings: Warning[];
  current: boolean;
  xsrc: boolean;
  onPick: (i: number) => void;
}) {
  const { t } = useTranslation(["storyboard", "terms"]);
  const s = p.slots[i]!;
  const a = s.asset ? p.assets[s.asset] : undefined;
  const lines = s.line_idx ?? [];
  const subs = lines.some((k) => p.lines[k]?.sub) && p.subtitles === "some";
  const instrumental = !s.lyric || s.lyric === "♪";
  const sharesWith = shot && shot.slots[0] !== i ? shot.slots[0]! : null;
  const todo = warnings.filter((w) => !w.reviewed);
  const flag = (kinds: string[]) => {
    const ws = warnings.filter((w) => kinds.includes(w.kind));
    return ws.length ? { w: ws[0]!, done: ws.every((w) => w.reviewed) } : null;
  };
  const sens = flag(["sensitive", "empty"]);
  const rep = flag(["repeat"]);
  const label = [
    t("tile.shot", { n: i + 1, time: fmtTime(s.start) }),
    todo.length && t("tile.hasWarnings"),
    s.locked && t("tile.pinned"),
    !s.asset && t("tile.noPhoto"),
  ]
    .filter(Boolean)
    .join(", ");
  return (
    <button
      type="button"
      className={`tile ${xsrc ? "xsrc" : ""}`}
      data-i={i}
      aria-current={current}
      aria-label={label}
      onClick={() => onPick(i)}
    >
      <ShotFrame project={p} shot={shot} slot={i} className="thumb">
        <span className="num">{i + 1}</span>
        <span className="flags">
          {sens && (
            <span
              className={`fl ${sens.done ? "rev" : "warn"}`}
              title={sens.done ? t("tile.reviewed", { text: sens.w.text }) : sens.w.text}
            >
              <TriangleAlert className="ico" aria-hidden />
            </span>
          )}
          {rep && (
            <span
              className={`fl ${rep.done ? "rev" : "warn"}`}
              title={rep.done ? t("tile.reviewed", { text: rep.w.text }) : rep.w.text}
            >
              <Repeat2 className="ico" aria-hidden />
            </span>
          )}
          {warnings.some((w) => w.kind === "pixelate") && (
            <span className="fl bad" title={t("terms:warnings.pixelate")}>
              <ZoomIn className="ico" aria-hidden />
            </span>
          )}
          {a?.video && (
            <span className="fl">
              <Film className="ico" aria-hidden />
              {Math.round(a.duration ?? 0)} s
            </span>
          )}
          {s.locked && (
            <span className="fl pin" title={t("tile.pinnedTitle")}>
              <Pin className="ico" aria-hidden />
            </span>
          )}
          {sharesWith != null && (
            <span className="fl" title={t("tile.sharesWith", { n: sharesWith + 1 })}>
              <Columns2 className="ico" aria-hidden />
              {sharesWith + 1}
            </span>
          )}
        </span>
        <span className="tm">{fmtTime(s.start)}</span>
      </ShotFrame>
      {instrumental ? (
        <div className="ly instr">{t("tile.instrumental")}</div>
      ) : (
        <div className="ly">
          {subs && (
            <>
              <Captions className="ico ico-sm cc" aria-label={t("tile.withSubtitle")} />{" "}
            </>
          )}
          {s.lyric_cont && <span className="cont">{t("tile.continues")}</span>}
          {s.lyric}
        </div>
      )}
    </button>
  );
});
