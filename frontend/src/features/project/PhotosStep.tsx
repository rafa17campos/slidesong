import { useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  Clapperboard,
  Film,
  Images,
  Info,
  Pin,
  RefreshCw,
  Search,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  TriangleAlert,
  Users,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link } from "react-router";

import { api, assetUrl } from "@/api/client";
import { applyProject, useAlbums, useCoverage, usePeople } from "@/api/queries";
import type { Motion, Order, Pace, Project, Sensitive, Subtitles, VideosMode } from "@/api/types";
import { useConfirm } from "@/components/ui/Confirm";
import { ProjectTuning } from "@/features/learning/ProjectTuning";
import { useToast } from "@/components/ui/Toast";
import i18n, { locale } from "@/i18n";
import { open as openWarnings, warningsFor } from "@/lib/storyboard";

import { useProjectCtx } from "./context";

const AVATAR = ["#3d6fb6", "#d45a4a", "#4f9a6a", "#9a6bb8", "#c98a2b", "#3d8f99", "#b8577f"];
const avatarColor = (name: string) =>
  AVATAR[[...name].reduce((a, c) => a + c.charCodeAt(0), 0) % AVATAR.length];

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Date shortcuts: this summer (last summer before June), the last six months, this whole year. */
export function dateShortcuts(now = new Date()): [string, string, string][] {
  const y = now.getMonth() < 5 ? now.getFullYear() - 1 : now.getFullYear();
  const six = new Date(now);
  six.setMonth(six.getMonth() - 6);
  const year = now.getFullYear();
  return [
    [i18n.t("photos:dates.shortcuts.summer"), `${y}-06-01`, `${y}-09-30`],
    [i18n.t("photos:dates.shortcuts.sixMonths"), iso(six), iso(now)],
    [i18n.t("photos:dates.shortcuts.year", { year }), `${year}-01-01`, `${year}-12-31`],
  ];
}

/**
 * A date field that is not remounted when it saves (typing the second digit of a day must not be lost):
 * uncontrolled, saved (debounced) once the date is whole, and updated from outside (shortcuts, undo, another
 * device) only while it is not being edited.
 */
function DateField({
  label,
  value,
  onChange,
  onDone,
}: {
  label: string;
  value: string | null;
  onChange: (v: string | null) => void;
  onDone: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el && document.activeElement !== el && el.value !== (value ?? "")) el.value = value ?? "";
  }, [value]);
  return (
    <input
      ref={ref}
      className="input"
      type="date"
      aria-label={label}
      defaultValue={value ?? ""}
      onChange={(e) => {
        const v = dateTyped(e.currentTarget);
        if (v !== undefined && v !== value) onChange(v);
      }}
      onBlur={onDone}
    />
  );
}

/**
 * The value of a date field once it is a whole date: undefined while it is being typed (the browser reports
 * a partial date as invalid, and the year goes through 0002, 0020, 0202…), null when cleared.
 */
export function dateTyped(el: { value: string; validity: { badInput: boolean } }): string | null | undefined {
  if (el.validity.badInput) return undefined;
  if (!el.value) return null;
  return Number(el.value.slice(0, 4)) >= 1990 ? el.value : undefined;
}

// the project fields behind each setting, and its name under photos:changed
const SUGGEST_FIELDS = [
  [["people"], "people"],
  [["date_from", "date_to"], "dates"],
  [["theme"], "theme"],
  [["avoid"], "avoid"],
  [["album_id"], "album"],
  [["shirtless"], "sensitive"],
  [["order", "flex_days"], "order"],
  [["videos"], "videos"],
  [["learned"], "learning"],
  [["tuning"], "tuning"],
] as const;

/** "a, b and c" in the interface language. */
const listOf = (xs: string[]) => new Intl.ListFormat(locale(), { type: "conjunction" }).format(xs);

/** The settings changed since the last suggestion (they only apply when suggesting again). */
export function changedSinceSuggest(p: Project): string[] {
  const was = p.suggested_with;
  if (!was || !p.slots.some((s) => s.asset)) return [];
  const empty = (v: unknown) =>
    v === undefined ||
    v === "" ||
    (!!v && typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length);
  const norm = (v: unknown) => JSON.stringify(empty(v) ? null : v);
  const now = p as unknown as Record<string, unknown>;
  return SUGGEST_FIELDS.filter(([ks]) => ks.some((k) => norm(now[k]) !== norm(was[k]))).map(([, name]) =>
    i18n.t(`photos:changed.${name}`),
  );
}

/** ② Photos: which photos (people, dates, theme, album), sensitive ones, how the story is told; a summary. */
export function PhotosStep() {
  const { t } = useTranslation("photos");
  const { project: p, plan, settings, suggest, busy, frozen, readOnly } = useProjectCtx();
  const set = settings.set;
  const [ask, confirmDialog] = useConfirm();
  const [tuning, setTuning] = useState(false);
  const photos = p.slots.filter((s) => s.asset).length;
  const pinned = p.slots.filter((s) => s.locked && s.asset).length;
  const changed = changedSinceSuggest(p);
  const videos = p.slots.filter((s) => s.asset && p.assets[s.asset]?.video).length;
  const warned = p.slots.filter((_, i) => openWarnings(warningsFor(p, plan, i)).length > 0).length;
  const sensitiveIn = p.slots.filter((_, i) =>
    warningsFor(p, plan, i).some((w) => w.kind === "sensitive"),
  ).length;

  const setPace = async (pace: Pace) => {
    if (pace === p.pace) return;
    if (photos) {
      const ok = await ask({
        title: t("pace.confirm.title"),
        body: t("pace.confirm.body"),
        confirm: t("pace.confirm.confirm"),
        tone: "warning",
      });
      if (!ok) return;
    }
    set({ pace });
  };

  return (
    <main className="pg-photos">
      <div className="wrap">
        {/* a blocked project: every setting shown, none can change */}
        <fieldset className="col ro" disabled={readOnly}>
          <section className="card-elevated p-6" aria-labelledby="f-who">
            <div className="card-head">
              <Users className="ico" aria-hidden />
              <h2 id="f-who">{t("who.title")}</h2>
            </div>
            <div className="set">
              <div className="k">
                {t("who.label")}
                <span className="hint">{t("who.hint")}</span>
              </div>
              <div className="v">
                <People project={p} onChange={(people) => set({ people })} />
              </div>
            </div>
            <div className="set">
              <div className="k">{t("dates.label")}</div>
              <div className="v">
                <div className="dates">
                  <DateField
                    label={t("dates.from")}
                    value={p.date_from ?? null}
                    onChange={(v) => set({ date_from: v }, { debounce: true })}
                    onDone={() => void settings.flush().catch(() => {})}
                  />
                  <span className="muted">→</span>
                  <DateField
                    label={t("dates.to")}
                    value={p.date_to ?? null}
                    onChange={(v) => set({ date_to: v }, { debounce: true })}
                    onDone={() => void settings.flush().catch(() => {})}
                  />
                </div>
                <div className="quick">
                  {dateShortcuts().map(([label, from, to]) => (
                    <button
                      key={label}
                      type="button"
                      className={`chip sm ${p.date_from === from && p.date_to === to ? "on" : ""}`}
                      onClick={() => set({ date_from: from, date_to: to })}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="set">
              <div className="k">
                {t("theme.label")}
                <span className="hint">{t("theme.hint")}</span>
              </div>
              <div className="v">
                <input
                  className="input"
                  value={p.theme ?? ""}
                  placeholder={t("theme.placeholder")}
                  onChange={(e) => set({ theme: e.target.value }, { debounce: true })}
                  maxLength={200}
                  onBlur={() => void settings.flush().catch(() => {})}
                />
              </div>
            </div>
            <div className="set">
              <div className="k">
                {t("avoid.label")}
                <span className="hint">{t("avoid.hint")}</span>
              </div>
              <div className="v">
                <input
                  className="input"
                  value={p.avoid ?? ""}
                  placeholder={t("avoid.placeholder")}
                  onChange={(e) => set({ avoid: e.target.value }, { debounce: true })}
                  maxLength={200}
                  onBlur={() => void settings.flush().catch(() => {})}
                />
              </div>
            </div>
            <div className="set">
              <div className="k">
                {t("album.label")}
                <span className="hint">{t("album.hint")}</span>
              </div>
              <div className="v">
                <AlbumPicker
                  value={p.album_id ?? null}
                  onChange={(album_id) => set({ album_id: album_id ?? "" })}
                />
                <div className="desc">{t("album.tip")}</div>
              </div>
            </div>
          </section>

          <section className="card-elevated p-6 privacy" aria-labelledby="f-care">
            <div className="card-head">
              <ShieldAlert className="ico" aria-hidden />
              <h2 id="f-care">{t("sensitive.title")}</h2>
              <span className="spacer" />
              {sensitiveIn > 0 && (
                <Link className="btn sm warning" to={`/p/${p.id}/storyboard`}>
                  <TriangleAlert className="ico ico-sm" aria-hidden />
                  {t("sensitive.inVideo", { count: sensitiveIn })}
                </Link>
              )}
            </div>
            <p className="card-sub" style={{ marginTop: -6 }}>
              <Trans
                t={t}
                i18nKey="sensitive.sub"
                components={{ icon: <TriangleAlert className="ico ico-sm warn-text" aria-hidden /> }}
              />
            </p>
            <Cards<Sensitive>
              label={t("sensitive.title")}
              value={(p.shirtless as Sensitive) ?? "show"}
              set={(shirtless) => set({ shirtless })}
              options={[
                ["show", t("sensitive.show.title"), t("sensitive.show.desc"), t("sensitive.show.tag")],
                ["avoid", t("sensitive.avoid.title"), t("sensitive.avoid.desc")],
                ["never", t("sensitive.never.title"), t("sensitive.never.desc")],
              ]}
            />
          </section>

          <section className="card-elevated p-6" aria-labelledby="f-how">
            <div className="card-head">
              <Clapperboard className="ico" aria-hidden />
              <h2 id="f-how">{t("how.title")}</h2>
            </div>
            <Setting k={t("pace.label")}>
              <Seg<Pace>
                label={t("pace.label")}
                value={(p.pace as Pace) ?? "normal"}
                set={(v) => void setPace(v)}
                options={[
                  ["slow", t("pace.slow")],
                  ["normal", t("pace.normal")],
                  ["fast", t("pace.fast")],
                ]}
              />
              <div className="desc">
                {t(`pace.desc.${(p.pace as Pace) ?? "normal"}`)}{" "}
                <Trans t={t} i18nKey="pace.more" components={{ b: <b /> }} />
              </div>
            </Setting>
            <Setting k={t("order.label")}>
              <Seg<Order>
                label={t("order.aria")}
                value={(p.order as Order) ?? "flex"}
                set={(order) => set({ order })}
                options={[
                  ["flex", t("order.flex")],
                  ["strict", t("order.strict")],
                  ["free", t("order.free")],
                ]}
              />
              {(p.order ?? "flex") === "flex" ? (
                <div className="row wrap">
                  <span className="desc">{t("order.flexLead")}</span>
                  <select
                    className="select"
                    style={{ width: "auto", minHeight: 32, padding: "4px 10px" }}
                    value={p.flex_days ?? 7}
                    onChange={(e) => set({ flex_days: +e.target.value })}
                    aria-label={t("order.margin")}
                  >
                    {(
                      [
                        [3, t("order.days3")],
                        [7, t("order.week1")],
                        [14, t("order.weeks2")],
                        [30, t("order.month1")],
                      ] as const
                    ).map(([v, label]) => (
                      <option key={v} value={v}>
                        {label}
                      </option>
                    ))}
                  </select>
                </div>
              ) : (
                <div className="desc">
                  {p.order === "strict" ? t("order.strictDesc") : t("order.freeDesc")}
                </div>
              )}
            </Setting>
            <Setting k={t("motion.label")} hint={t("motion.hint")}>
              <Seg<Motion>
                label={t("motion.aria")}
                value={(p.motion as Motion) ?? "normal"}
                set={(motion) => set({ motion })}
                options={[
                  ["calm", t("motion.calm")],
                  ["normal", t("motion.normal")],
                  ["lively", t("motion.lively")],
                ]}
              />
              <div className="desc">{t("motion.desc")}</div>
            </Setting>
            <Setting k={t("videos.label")}>
              <Seg<VideosMode>
                label={t("videos.label")}
                value={(p.videos as VideosMode) ?? "some"}
                set={(videos) => set({ videos })}
                options={[
                  ["off", t("videos.off")],
                  ["some", t("videos.some")],
                  ["many", t("videos.many")],
                ]}
              />
              <div className="desc">{t("videos.desc")}</div>
            </Setting>
            <Setting k={t("opening.label")} hint={t("opening.hint")}>
              <div className="row top" style={{ gap: 12, flexWrap: "wrap" }}>
                <input
                  className="input grow"
                  style={{ minWidth: 180 }}
                  value={p.title_overlay ?? ""}
                  placeholder={t("opening.placeholder")}
                  onChange={(e) => set({ title_overlay: e.target.value }, { debounce: true })}
                  maxLength={120}
                  onBlur={() => void settings.flush().catch(() => {})}
                />
                {p.title_overlay && p.slots[0]?.asset && (
                  <div
                    className="overlay-prev photo frame-169"
                    aria-hidden
                    style={{ backgroundImage: `url(${assetUrl(p.slots[0].asset)})` }}
                  >
                    <span className="txt">{p.title_overlay}</span>
                  </div>
                )}
              </div>
            </Setting>
            <Setting k={t("subtitles.label")} hint={t("subtitles.hint")}>
              <Seg<Subtitles>
                label={t("subtitles.label")}
                value={(p.subtitles as Subtitles) ?? "off"}
                set={(subtitles) => set({ subtitles })}
                options={[
                  ["off", t("subtitles.off")],
                  ["all", t("subtitles.all")],
                  ["some", t("subtitles.some")],
                ]}
              />
              <div className="desc">
                {(p.subtitles ?? "off") === "some"
                  ? t("subtitles.desc.some", { count: p.lines.filter((l) => l.sub).length })
                  : (p.subtitles ?? "off") === "all"
                    ? t("subtitles.desc.all")
                    : t("subtitles.desc.off")}
              </div>
            </Setting>
            <Setting k={t("learning.label")} hint={t("learning.hint")}>
              <Seg<"on" | "off">
                label={t("learning.label")}
                value={p.learned === false ? "off" : "on"}
                set={(v) => set({ learned: v === "on" })}
                options={[
                  ["on", t("learning.on")],
                  ["off", t("learning.off")],
                ]}
              />
              <div className="desc">{t("learning.desc")}</div>
              <div className="row wrap" style={{ gap: 8, marginTop: 10 }}>
                <button type="button" className="btn sm" onClick={() => setTuning(true)}>
                  <SlidersHorizontal className="ico ico-sm" aria-hidden />
                  {t("learning.tuning")}
                  {Object.keys(p.tuning ?? {}).length > 0 && ` (${Object.keys(p.tuning ?? {}).length})`}
                </button>
                <Link className="btn sm ghost" to="/learning">
                  {t("learning.seeLearned")}
                </Link>
              </div>
              <ProjectTuning
                open={tuning}
                onClose={() => setTuning(false)}
                value={p.tuning ?? {}}
                onChange={(tuning) => set({ tuning })}
                disabled={readOnly}
              />
            </Setting>
          </section>
        </fieldset>

        <aside className="col aside">
          <section className="card-default p-5" aria-labelledby="f-sum">
            <div className="card-head" style={{ marginBottom: 6 }}>
              <h3 id="f-sum">{t("summary.title")}</h3>
            </div>
            <div className="sum-row">
              <Images className="ico ico-sm" aria-hidden />
              {t("summary.withPhoto")}
              <span className="n">{p.slots.length ? `${photos} / ${p.slots.length}` : "—"}</span>
            </div>
            <div className="sum-row">
              <Pin className="ico ico-sm" aria-hidden />
              {t("summary.pinned")}
              <span className="n">{pinned}</span>
            </div>
            <div className="sum-row">
              <Film className="ico ico-sm" aria-hidden />
              {t("summary.videos")}
              <span className="n">{videos}</span>
            </div>
            <div className="sum-row">
              <TriangleAlert className="ico ico-sm" aria-hidden />
              {t("summary.warned")}
              <span className={`n ${warned ? "warn-text" : ""}`}>{warned}</span>
            </div>
            {changed.length > 0 && !frozen && (
              <div className="callout info" style={{ marginTop: 12 }}>
                <Info className="ico" aria-hidden />
                <div>
                  <Trans
                    t={t}
                    i18nKey="summary.changed"
                    values={{ list: listOf(changed) }}
                    components={{ b: <b /> }}
                  />
                </div>
              </div>
            )}
            {frozen ? null : p.slots.length ? (
              <>
                <button
                  type="button"
                  className="btn primary w-full"
                  style={{ marginTop: 12 }}
                  disabled={busy}
                  onClick={() => void suggest()}
                >
                  <Sparkles className="ico" aria-hidden />
                  {photos ? t("suggest.again") : t("suggest.first")}
                </button>
                <p className="text-caption muted" style={{ margin: "8px 2px 0", textAlign: "center" }}>
                  {photos
                    ? pinned
                      ? t("suggest.keepsPinned", { count: pinned })
                      : t("suggest.mayChangeAll")
                    : t("suggest.firstHint")}
                </p>
              </>
            ) : (
              <p className="text-small muted" style={{ marginTop: 12 }}>
                <Trans
                  t={t}
                  i18nKey="suggest.needsSong"
                  components={{ link: <Link to={`/p/${p.id}/song`} /> }}
                />
              </p>
            )}
          </section>
          <Candidates project={p} />
          <Excluded project={p} frozen={readOnly} />
        </aside>
      </div>
      {confirmDialog}
    </main>
  );
}

function Setting({ k, hint, children }: { k: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="set">
      <div className="k">
        {k}
        {hint && <span className="hint">{hint}</span>}
      </div>
      <div className="v">{children}</div>
    </div>
  );
}

function Seg<T extends string>({
  label,
  value,
  options,
  set,
}: {
  label: string;
  value: T;
  options: [T, string][];
  set: (v: T) => void;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map(([v, t]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => set(v)}>
          {t}
        </button>
      ))}
    </div>
  );
}

function Cards<T extends string>({
  label,
  value,
  options,
  set,
}: {
  label: string;
  value: T;
  options: [T, string, string, string?][];
  set: (v: T) => void;
}) {
  return (
    <div className="radios" role="radiogroup" aria-label={label}>
      {options.map(([v, t, d, tag]) => (
        <button
          key={v}
          type="button"
          className="rcard"
          role="radio"
          aria-checked={value === v}
          onClick={() => set(v)}
        >
          {tag && <span className="badge rec">{tag}</span>}
          <b>{t}</b>
          <span className="d">{d}</span>
        </button>
      ))}
    </div>
  );
}

function People({ project: p, onChange }: { project: Project; onChange: (people: string[]) => void }) {
  const { t } = useTranslation("photos");
  const { data: all } = usePeople();
  const [q, setQ] = useState("");
  const sel = useMemo(() => p.people ?? [], [p.people]);
  const add = (n: string) => {
    onChange([...sel, n]);
    setQ("");
  };
  const matches = useMemo(() => {
    const norm = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
    return q
      ? (all ?? []).filter((x) => !sel.includes(x.name) && norm(x.name).includes(norm(q))).slice(0, 8)
      : [];
  }, [q, all, sel]);
  // "most frequent": by how many of your projects they are in
  const top = (all ?? [])
    .filter((x) => !sel.includes(x.name) && x.used > 0)
    .sort((a, b) => b.used - a.used)
    .slice(0, 4);
  return (
    <>
      <div className="people-sel">
        {sel.map((n) => (
          <button
            key={n}
            type="button"
            className="chip on"
            aria-label={t("people.remove", { name: n })}
            onClick={() => onChange(sel.filter((x) => x !== n))}
          >
            <span className="avatar" style={{ background: avatarColor(n) }}>
              {n[0]}
            </span>
            {n} <X className="ico ico-sm x" aria-hidden />
          </button>
        ))}
        {!sel.length && <span className="muted text-small">{t("people.none")}</span>}
      </div>
      <div style={{ position: "relative" }}>
        <label className="input-ico">
          <Search className="ico" aria-hidden />
          <span className="sr-only">{t("people.add")}</span>
          <input
            className="input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && matches[0] && (e.preventDefault(), add(matches[0].name))}
            placeholder={all ? t("people.placeholderCount", { n: all.length }) : t("people.placeholder")}
          />
        </label>
        {matches.length > 0 && (
          <div
            className="popover menu"
            style={{ position: "absolute", left: 0, right: 0, top: "calc(100% + 4px)", zIndex: 10 }}
          >
            {matches.map((x) => (
              <button key={x.name} type="button" onClick={() => add(x.name)}>
                <span className="avatar" style={{ background: avatarColor(x.name), marginLeft: 0 }}>
                  {x.name[0]}
                </span>
                {x.name}
              </button>
            ))}
          </div>
        )}
      </div>
      {top.length > 0 && (
        <div className="quick">
          <span className="lbl">{t("people.top")}</span>
          {top.map((x) => (
            <button key={x.name} type="button" className="chip sm" onClick={() => add(x.name)}>
              + {x.name}
            </button>
          ))}
        </div>
      )}
    </>
  );
}

function AlbumPicker({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
  const { t } = useTranslation("photos");
  const { data, refetch, isFetching } = useAlbums();
  return (
    <div className="row">
      <select
        className="select grow"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        aria-label={t("album.label")}
      >
        <option value="">{t("album.none")}</option>
        {data?.map((a) => (
          <option key={a.id} value={a.id}>
            {t("album.option", { name: a.name, count: a.count })}
          </option>
        ))}
        {value && !data?.some((a) => a.id === value) && <option value={value}>{t("album.chosen")}</option>}
      </select>
      <button
        type="button"
        className="icon-btn"
        aria-label={t("album.refresh")}
        title={t("album.refresh")}
        onClick={() => void refetch()}
        disabled={isFetching}
      >
        <RefreshCw className={`ico ${isFetching ? "spin" : ""}`} />
      </button>
    </div>
  );
}

function Excluded({ project: p, frozen }: { project: Project; frozen: boolean }) {
  const { t } = useTranslation("photos");
  const qc = useQueryClient();
  const toast = useToast();
  if (!p.excluded.length) return null;
  const back = async (asset: string) => {
    try {
      const fd = new FormData();
      fd.append("asset", asset);
      const r = await api.post<Project>(`/api/projects/${p.id}/unexclude`, fd);
      applyProject(qc, p.id, r);
      toast({ text: t("excluded.restored") });
    } catch (e) {
      toast({ text: (e as Error).message, tone: "error" });
    }
  };
  return (
    <section className="card-default p-5" aria-labelledby="f-out">
      <div className="card-head" style={{ marginBottom: 8 }}>
        <Ban className="ico ico-sm" aria-hidden />
        <h3 id="f-out">{t("excluded.title")}</h3>
        <span className="badge">{p.excluded.length}</span>
      </div>
      <div className="tray">
        {p.excluded.map((a) => (
          <button
            key={a}
            type="button"
            aria-label={t("excluded.restore")}
            title={t("excluded.restoreShort")}
            style={{ backgroundImage: `url(${assetUrl(a)})` }}
            disabled={frozen}
            onClick={() => void back(a)}
          />
        ))}
      </div>
      <p className="text-caption muted" style={{ margin: "8px 0 0" }}>
        {t("excluded.hint")}
      </p>
    </section>
  );
}

/** The candidate photos and how many are analysed on the GPU; a warning when some are not and the GPU worker is off. */
function Candidates({ project: p }: { project: Project }) {
  const { t } = useTranslation("photos");
  const filtered = !!(p.people?.length || p.date_from || p.date_to || p.album_id);
  const { data: c, isFetching } = useCoverage(p, filtered);
  const prep = p.prep?.state === "running" && p.prep.total ? p.prep : null;
  if (!c && !prep && isFetching)
    return (
      <section className="card-default p-5" aria-labelledby="f-pool">
        <div className="card-head" style={{ marginBottom: 8 }}>
          <h3 id="f-pool">{t("pool.title")}</h3>
        </div>
        <p className="text-small muted" style={{ margin: 0 }}>
          {t("pool.counting")}
        </p>
      </section>
    );
  if (!c?.pool && !prep) return null;
  const total = prep?.total ?? c?.pool ?? 0;
  const done = prep ? (prep.done ?? 0) : Math.max(0, (c?.pool ?? 0) - (c?.pending ?? 0));
  const offline = !!c && c.pending > 0 && !c.can_analyse && !prep;
  return (
    <section className="card-default p-5" aria-labelledby="f-pool">
      <div className="card-head" style={{ marginBottom: 8 }}>
        <h3 id="f-pool">{t("pool.title")}</h3>
      </div>
      <div className="text-small">
        <Trans t={t} i18nKey="pool.total" count={total} components={{ b: <b className="tnum" /> }} />
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <span className="text-caption muted">{t("pool.analyzed")}</span>
        <span className="spacer" />
        <span className="text-caption strong tnum">{t("pool.progress", { done, total })}</span>
      </div>
      <div className="meter" style={{ marginTop: 4 }}>
        <i style={{ width: `${total ? Math.round((done / total) * 100) : 0}%` }} />
      </div>
      {offline ? (
        <div className="callout warn" style={{ marginTop: 12 }}>
          <TriangleAlert className="ico" aria-hidden />
          <div>
            <Trans
              t={t}
              i18nKey="pool.offline"
              values={{ name: c!.name, n: c!.pending }}
              components={{ b: <b /> }}
            />
          </div>
        </div>
      ) : (
        <p className="text-caption muted" style={{ margin: "6px 0 0" }}>
          {t("pool.note")}
          {prep ? ` ${t("pool.analyzingNow")}` : c && c.pending > 0 ? ` ${t("pool.onSuggest")}` : ""}
        </p>
      )}
    </section>
  );
}
