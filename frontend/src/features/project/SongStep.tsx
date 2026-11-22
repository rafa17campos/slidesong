import { useQueryClient } from "@tanstack/react-query";
import { Captions, Image, Music, RefreshCw, Sparkles, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { locale } from "@/i18n";

import { api } from "@/api/client";
import { applyProject, useConfig } from "@/api/queries";
import type { Project } from "@/api/types";
import { useConfirm } from "@/components/ui/Confirm";
import { useToast } from "@/components/ui/Toast";
import { SongMap } from "@/features/storyboard/SongMap";
import { energy, SECTION_COLOR, sectionKindName, sectionName } from "@/lib/names";
import { fmtTime, sectionsFromLines, shotsOfLines } from "@/lib/storyboard";

import { useProjectCtx } from "./context";

/** ① Song: the MP3, its analysis and structure, and the lyrics (synced, or as text to edit). */
export function SongStep() {
  const { t } = useTranslation(["song", "common"]);
  const { project: p, settings, analyze, busy, frozen, readOnly } = useProjectCtx();
  const [view, setView] = useState<"synced" | "text">(p.lines.length ? "synced" : "text");
  const sections = sectionsFromLines(p);
  const analyzed = p.slots.length > 0;
  return (
    <main className="pg-song">
      <div className="wrap">
        <div className="col sticky-col">
          <section className="card-elevated p-6" aria-label={t("common:steps.song")}>
            <fieldset className="ro" disabled={readOnly}>
              <label className="field" style={{ marginBottom: 18 }}>
                <span className="label">{t("projectTitle")}</span>
                <input
                  className="input"
                  value={p.title}
                  onChange={(e) => settings.set({ title: e.target.value }, { debounce: true })}
                  maxLength={120}
                  onBlur={() => void settings.flush().catch(() => {})}
                />
              </label>
            </fieldset>
            <SongFile project={p} busy={busy} frozen={frozen} />
            {p.song && (
              <audio
                controls
                preload="metadata"
                src={`/api/projects/${p.id}/files/${p.song.file}?v=${encodeURIComponent(p.song.uploaded ?? `${p.song.name}-${p.song.duration}`)}`}
                style={{ width: "100%", margin: "16px 0 4px" }}
              />
            )}
            {p.song && (
              <div className="kpis k4" style={{ marginTop: 14 }}>
                <Kpi v={fmtTime(p.song.duration)} k={t("kpi.duration")} />
                <Kpi v={p.song.tempo ? String(Math.round(p.song.tempo)) : "—"} k={t("kpi.bpm")} />
                <Kpi v={String(p.lines.length || "—")} k={t("kpi.lines")} />
                <Kpi v={String(p.slots.length || "—")} k={t("kpi.shots")} />
              </div>
            )}
            {p.song && !frozen && (
              <>
                <hr className="divider" />
                {analyzed ? (
                  <div className="row top">
                    <RefreshCw className="ico muted" aria-hidden />
                    <div className="grow text-small">
                      <b>{t("reanalyze.title")}</b>
                      <div className="muted">{t("reanalyze.hint")}</div>
                    </div>
                    <button
                      type="button"
                      className="btn sm warning"
                      style={{ flex: "none" }}
                      disabled={busy}
                      onClick={() => void analyze()}
                    >
                      {t("reanalyze.button")}
                    </button>
                  </div>
                ) : (
                  <div className="row top">
                    <Sparkles className="ico muted" aria-hidden />
                    <div className="grow text-small">
                      <b>{t("analyze.title")}</b>
                      <div className="muted">{t("analyze.hint")}</div>
                    </div>
                    <button
                      type="button"
                      className="btn sm primary"
                      style={{ flex: "none" }}
                      disabled={busy}
                      onClick={() => void analyze()}
                    >
                      {t("analyze.button")}
                    </button>
                  </div>
                )}
              </>
            )}
          </section>
          {sections.length > 0 && (
            <section className="card-default p-6 bigmap" aria-label={t("structure.title")}>
              <div className="card-head">
                <h3>{t("structure.title")}</h3>
                <span className="muted text-small">{t("structure.hint")}</span>
              </div>
              <SongMap
                project={p}
                groups={sections.map((x) => x.group)}
                warned={[]}
                current={null}
                onSection={(k) =>
                  document.getElementById(`lsec-${k}`)?.scrollIntoView({ behavior: "smooth", block: "start" })
                }
              />
              <div className="legend">
                {["verse", "chorus", "bridge", "intro", "outro"].map((k) => (
                  <span key={k}>
                    <i style={{ background: SECTION_COLOR[k] }} />
                    {sectionKindName(k)}
                  </span>
                ))}
                <span className="muted">{t("structure.height")}</span>
              </div>
            </section>
          )}
        </div>

        <div className="col">
          <section className="card-elevated p-6" aria-label={t("lyrics.title")}>
            <div className="card-head" style={{ flexWrap: "wrap" }}>
              <h2>{t("lyrics.title")}</h2>
              <span className="spacer" />
              {p.lines.length > 0 && (
                <div className="seg" role="group" aria-label={t("lyrics.view")}>
                  <button type="button" aria-pressed={view === "synced"} onClick={() => setView("synced")}>
                    {t("lyrics.synced")}
                  </button>
                  <button type="button" aria-pressed={view === "text"} onClick={() => setView("text")}>
                    {t("lyrics.edit")}
                  </button>
                </div>
              )}
            </div>
            <LyricsLanguage />
            {view === "text" ? (
              <>
                <p className="card-sub">
                  {t("lyrics.pasteHint")}
                  {analyzed && t("lyrics.reanalyzeHint")}
                </p>
                <textarea
                  disabled={readOnly}
                  className="textarea"
                  style={{ minHeight: 420 }}
                  value={p.lyrics ?? ""}
                  placeholder={t("lyrics.placeholder")}
                  onChange={(e) => settings.set({ lyrics: e.target.value }, { debounce: true })}
                  maxLength={20000}
                  onBlur={() => void settings.flush().catch(() => {})}
                />
              </>
            ) : (
              <SyncedLyrics project={p} sections={sections} frozen={readOnly} />
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

/** «Sung in: Automatic (Spanish) ▾»: what Whisper, Claude and the word lists read the lyrics as. */
function LyricsLanguage() {
  const { t } = useTranslation("song");
  const { project: p, settings, readOnly } = useProjectCtx();
  const names = new Intl.DisplayNames([locale()], { type: "language" });
  const name = (code: string) => {
    const n = names.of(code) ?? code;
    return n.charAt(0).toLocaleUpperCase(locale()) + n.slice(1);
  };
  const value = p.lyrics_lang ?? "auto";
  // the languages the server can read songs in (slidesong/languages/)
  const songLanguages = useConfig().data?.song_languages ?? [];
  return (
    <div
      style={{ display: "flex", flexWrap: "wrap", gap: "6px 10px", margin: "0 0 14px", alignItems: "center" }}
    >
      <label className="text-small strong" htmlFor="lyrics-lang">
        {t("language.label")}
      </label>
      <select
        id="lyrics-lang"
        className="select"
        style={{ width: "auto" }}
        value={value}
        disabled={readOnly}
        onChange={(e) => settings.set({ lyrics_lang: e.target.value })}
      >
        <option value="auto">
          {p.lyrics_detected
            ? t("language.autoDetected", { name: name(p.lyrics_detected) })
            : t("language.auto")}
        </option>
        {songLanguages.map((c) => (
          <option key={c} value={c}>
            {name(c)}
          </option>
        ))}
      </select>
      <span className="text-caption muted" style={{ flexBasis: "100%" }}>
        {p.lines.length > 0 ? t("language.hintAnalyzed") : t("language.hint")}
      </span>
    </div>
  );
}

function Kpi({ v, k }: { v: string; k: string }) {
  return (
    <div className="card-flat kpi">
      <div className="v">{v}</div>
      <div className="k">{k}</div>
    </div>
  );
}

function SongFile({ project: p, busy, frozen }: { project: Project; busy: boolean; frozen: boolean }) {
  const { t } = useTranslation(["song", "common"]);
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  const [ask, confirmDialog] = useConfirm();
  const upload = async (f: File) => {
    if (p.slots.some((s) => s.asset)) {
      const ok = await ask({
        title: t("file.confirm.title"),
        body: t("file.confirm.body"),
        confirm: t("file.confirm.confirm"),
        tone: "warning",
      });
      if (!ok) {
        if (input.current) input.current.value = "";
        return;
      }
    }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await api.post<Project>(`/api/projects/${p.id}/song`, fd);
      applyProject(qc, p.id, r);
      toast({ text: t("file.uploaded") });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  };
  return (
    <div className="file">
      <span className="tile-ico">
        <Music className="ico" aria-hidden />
      </span>
      <div className="grow" style={{ minWidth: 0 }}>
        <h2 className="truncate" style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>
          {p.song ? p.song.name : t("file.none")}
        </h2>
        <div className="muted text-small">
          {p.song
            ? `${fmtTime(p.song.duration)}${p.song.tempo ? ` · ${Math.round(p.song.tempo)} BPM` : ""}`
            : t("file.formats")}
        </div>
      </div>
      {!frozen && (
        <>
          <button
            type="button"
            className={`btn sm ${p.song ? "ghost" : "primary"}`}
            disabled={busy || uploading}
            onClick={() => input.current?.click()}
          >
            <Upload className="ico ico-sm" aria-hidden />
            {uploading ? t("file.uploading") : p.song ? t("file.change") : t("file.upload")}
          </button>
          <input
            ref={input}
            type="file"
            accept="audio/*"
            hidden
            onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])}
          />
        </>
      )}
      {confirmDialog}
    </div>
  );
}

function SyncedLyrics({
  project: p,
  sections,
  frozen,
}: {
  project: Project;
  sections: ReturnType<typeof sectionsFromLines>;
  frozen: boolean;
}) {
  const { t } = useTranslation(["song", "common"]);
  const qc = useQueryClient();
  const toast = useToast();
  const shots = shotsOfLines(p);
  const choose = p.subtitles === "some" && !frozen;
  const toggle = async (k: number, on: boolean) => {
    try {
      const r = await api.post<Project>(`/api/projects/${p.id}/lines/${k}/sub`, { on });
      applyProject(qc, p.id, r, { plan: false });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  return (
    <>
      <p className="card-sub">
        {t("lyrics.syncedHint")}
        {choose ? t("lyrics.subHint") : ""}
      </p>
      <div className="lines">
        {sections.map((x, n) => (
          <div key={n}>
            <div className="sec-h" id={`lsec-${n}`}>
              <span
                className="sec-pill"
                style={{ ["--c" as string]: SECTION_COLOR[x.group.section?.kind ?? "verse"] }}
              >
                {sectionName(x.group.section)}
              </span>
              <span className="muted text-small tnum">
                {fmtTime(x.group.from)} – {fmtTime(x.group.to)}
              </span>
              {x.group.section?.mood && (
                <span className="subtle text-small">· {energy(x.group.section.mood)}</span>
              )}
            </div>
            {x.lines.map((k) => {
              const l = p.lines[k]!;
              const sh = shots.get(k) ?? [];
              return (
                <div key={k} className="ln">
                  <span className="t">{fmtTime(l.start)}</span>
                  <div>
                    <div className="orig">{l.text}</div>
                    {l.ai?.english && <div className="en">{l.ai.english}</div>}
                    {l.ai?.visual && (
                      <div className="idea">
                        <Image className="ico ico-sm" aria-hidden />
                        <span>{l.ai.visual}</span>
                      </div>
                    )}
                  </div>
                  <div className="side">
                    {choose && (
                      <button
                        type="button"
                        className={`icon-btn sm bare cc ${l.sub ? "" : "off"}`}
                        aria-pressed={!!l.sub}
                        aria-label={t("lyrics.sub", { line: l.text })}
                        onClick={() => void toggle(k, !l.sub)}
                      >
                        <Captions className="ico" />
                      </button>
                    )}
                    {sh.length > 0 && (
                      <span className="badge">
                        {t("lyrics.shots", { count: sh.length, list: sh.map((i) => i + 1).join(", ") })}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </>
  );
}
