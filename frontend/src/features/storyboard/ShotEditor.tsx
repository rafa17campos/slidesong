import {
  ArrowLeftRight,
  ArrowRight,
  Ban,
  Calendar,
  Captions,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardPaste,
  Ellipsis,
  Film,
  Image,
  Images,
  Info,
  Lock,
  Move,
  Pencil,
  Pin,
  Play,
  Redo2,
  Repeat2,
  RotateCcw,
  ScanFace,
  Shuffle,
  Sparkles,
  TriangleAlert,
  Undo2,
  X,
  ZoomIn,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Trans, useTranslation } from "react-i18next";

import { assetUrl } from "@/api/client";
import { useHistoryStep } from "@/api/queries";
import { useUndoToast } from "@/hooks/useUndoToast";
import { blocksEdits } from "@/lib/jobs";
import type { Boundary, Plan, Project, Shot } from "@/api/types";
import { Dialog } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";
import { locale } from "@/i18n";
import {
  isPortrait,
  isQualityWarning,
  lookName,
  lookLabel,
  lookOptions,
  pairFrom,
  SECTION_COLOR,
  sectionName,
  transitionName,
  transitions,
} from "@/lib/names";
import { fmtTime, moveState, type Group, type Warning } from "@/lib/storyboard";

import { immichIdFrom, makeSnippet, useBurst, useShotActions, type SlotChange } from "./actions";
import { Chooser } from "./Chooser";
import { ShotFrame } from "./ShotFrame";

export interface EditorProps {
  project: Project;
  plan: Plan | undefined;
  i: number;
  shot: Shot | undefined;
  group: Group | undefined;
  warnings: Warning[];
  mobile: boolean;
  onStep: (d: -1 | 1) => void;
  onClose?: () => void;
  onGoto: (i: number) => void;
  onExchange: (i: number) => void;
  onChange: (i: number) => void; // open "Cambiar foto"
  onSnippet: (i: number) => void; // play ~6 s of the shot with its music
  onInfo: (id: string, slot: number) => void; // «Photo details»
  /** blocked project: look, play and read, but no edits */
  readOnly?: boolean;
  /** «Warning 2 of 4» while walking the warnings */
  counter?: string | null;
  hasPrev?: boolean;
  hasNext?: boolean;
}

const LOOK_ICON: Record<string, ReactNode> = {
  polaroid: <Image className="ico" />,
  polaroid_pair: <Images className="ico" />,
  diptych: <Images className="ico" />,
  face_to_whole: <ScanFace className="ico" />,
  whole_to_face: <ScanFace className="ico" />,
};

const fmtDate = (d: string | undefined) =>
  d ? new Date(d).toLocaleDateString(locale(), { day: "numeric", month: "long", year: "numeric" }) : "";

export function ShotEditor(props: EditorProps) {
  const {
    project: p,
    plan,
    i,
    shot,
    group,
    warnings,
    mobile,
    onStep,
    onClose,
    onGoto,
    onExchange,
    onChange,
    onSnippet,
    onInfo,
    readOnly = false,
    counter = null,
    hasPrev = i > 0,
    hasNext = i < p.slots.length - 1,
  } = props;
  const { t } = useTranslation(["storyboard", "common"]);
  const s = p.slots[i]!;
  const a = s.asset ? p.assets[s.asset] : undefined;
  const act = useShotActions(p.id);
  const toast = useToast();
  const [more, setMore] = useState(false);
  const first = shot?.slots[0] ?? i;

  const fail = (e: Error) => toast({ text: e.message, tone: "error" });
  const undoToast = useUndoToast(p.id);
  const swipe = useRef<{ x: number; y: number } | null>(null);
  const history = useHistoryStep(p.id);
  // one at a time, and saying which photo it is about: a double tap must not also take out the replacement
  const busy = act.slot.isPending;
  const change = (c: SlotChange, done?: string) =>
    !busy &&
    act.slot.mutate(
      { i, change: { ...c, expect: s.asset ?? undefined } },
      { onError: fail, onSuccess: (r) => done && undoToast(done, r) },
    );

  const pin = () => change({ action: s.locked ? "unlock" : "lock" });
  const reject = () => change({ action: "reject" }, t("toasts.rejected", { n: i + 1 }));
  const pickBurst = (id: string) =>
    change({ action: "set", asset: id, source: "burst" }, t("toasts.burst", { n: i + 1 }));
  const paste = async () => {
    try {
      const id = immichIdFrom(await navigator.clipboard.readText());
      if (!id) return toast({ text: t("toasts.noLink"), tone: "error" });
      change({ action: "set", asset: id, source: "immich" }, t("toasts.immich", { n: i + 1 }));
    } catch {
      toast({ text: t("toasts.noClipboard"), tone: "error" });
    }
  };

  const sec = group?.section;
  const total = p.slots.length;
  const lines = s.line_idx ?? [];
  const subsOn = lines.length > 0 && lines.every((k) => p.lines[k]?.sub);
  const instrumental = !s.lyric || s.lyric === "♪";
  const why = s.asset ? (s.why?.[s.asset] ?? []) : [];

  const head = (
    <div className="insp-head">
      {mobile && (
        <button
          type="button"
          className="icon-btn bare"
          aria-label={t("common:actions.close")}
          onClick={onClose}
        >
          <X className="ico" />
        </button>
      )}
      <h2 tabIndex={-1}>
        {counter && (
          <span className="warn-text" style={{ fontWeight: 600 }}>
            {counter} ·{" "}
          </span>
        )}
        <Trans
          t={t}
          i18nKey="shot.heading"
          values={{ n: i + 1, total }}
          components={{ m: <span className="muted" style={{ fontWeight: 500 }} /> }}
        />
      </h2>
      <span className="muted text-small tnum">
        {fmtTime(s.start)}–{fmtTime(s.end)}
      </span>
      {sec && !counter && (
        <span className="sec-pill hide-mobile" style={{ ["--c" as string]: SECTION_COLOR[sec.kind] }}>
          {sectionName(sec)}
        </span>
      )}
      <span className="spacer" />
      <button
        type="button"
        className="icon-btn"
        aria-label={t("shot.prev")}
        onClick={() => onStep(-1)}
        disabled={!hasPrev}
      >
        <ChevronLeft className="ico" />
      </button>
      <button
        type="button"
        className="icon-btn"
        aria-label={t("shot.next")}
        onClick={() => onStep(1)}
        disabled={!hasNext}
      >
        <ChevronRight className="ico" />
      </button>
    </div>
  );

  const body = (
    <>
      <div
        // phones: swipe the photo sideways to go to the previous / next shot
        style={mobile ? { touchAction: "pan-y" } : undefined}
        onPointerDown={mobile ? (e) => (swipe.current = { x: e.clientX, y: e.clientY }) : undefined}
        onPointerUp={
          mobile
            ? (e) => {
                const from = swipe.current;
                swipe.current = null;
                if (!from) return;
                const dx = e.clientX - from.x;
                const dy = e.clientY - from.y;
                if (Math.abs(dx) > 60 && Math.abs(dy) < 50) {
                  if (dx < 0 && hasNext) onStep(1);
                  if (dx > 0 && hasPrev) onStep(-1);
                }
              }
            : undefined
        }
        onPointerCancel={() => (swipe.current = null)}
      >
        <ShotFrame project={p} shot={shot} slot={i} big className="insp-media" />
      </div>
      <div className="media-bar">
        <button
          type="button"
          className="btn sm"
          onClick={() => onSnippet(i)}
          disabled={!s.asset || !!p.running}
        >
          <Play className="ico ico-sm" aria-hidden /> {t("editor.play")}
        </button>
        <span className="spacer" />
        {s.asset && (
          <button type="button" className="btn sm ghost" onClick={() => onInfo(s.asset!, i)}>
            <Info className="ico ico-sm" aria-hidden /> {t("editor.photoDetails")}
          </button>
        )}
      </div>

      <div className="lyric">
        {instrumental ? (
          <q style={{ quotes: "none" }} className="muted">
            {t("editor.instrumental")}
          </q>
        ) : (
          <>
            <q>
              {s.lyric_cont && <span className="cont">{t("editor.lineContinues")}</span>}
              {s.lyric}
            </q>
            {p.subtitles === "some" && lines.length > 0 && (
              <label className="subtoggle">
                <Captions className="ico ico-sm" aria-hidden />
                {t("editor.subtitle")}
                <button
                  type="button"
                  className="switch"
                  role="switch"
                  aria-checked={subsOn}
                  aria-label={t("editor.subtitleHere")}
                  disabled={readOnly}
                  onClick={() => act.subs.mutate({ i, on: !subsOn }, { onError: fail })}
                />
              </label>
            )}
          </>
        )}
      </div>

      {warnings.map((w, k) => (
        <WarningCallout
          key={k}
          w={w}
          onChange={() => onChange(i)}
          onGoto={onGoto}
          onAuto={() => act.move.mutate({ slot: first, factor: null }, { onError: fail })}
          readOnly={readOnly}
        />
      ))}

      {!mobile && !readOnly && (
        <div className="acts">
          <button type="button" className="btn soft-primary main" onClick={() => onChange(i)}>
            <Images className="ico" aria-hidden /> {t("editor.changePhoto")}
          </button>
          <button
            type="button"
            className={`icon-btn ${s.locked ? "on" : ""}`}
            aria-pressed={!!s.locked}
            aria-label={s.locked ? t("editor.unpinPhoto") : t("editor.pinPhoto")}
            title={s.locked ? t("editor.pinnedTitle") : t("editor.pinTitle")}
            onClick={pin}
            disabled={!s.asset || busy}
          >
            <Pin className="ico" />
          </button>
          <button
            type="button"
            className="icon-btn"
            aria-label={t("editor.swap")}
            title={t("editor.swap")}
            onClick={() => onExchange(i)}
            disabled={!s.asset || busy}
          >
            <ArrowLeftRight className="ico" />
          </button>
          <button
            type="button"
            className="icon-btn"
            aria-label={t("editor.paste")}
            title={t("editor.paste")}
            onClick={paste}
          >
            <ClipboardPaste className="ico" />
          </button>
          <button
            type="button"
            className="btn danger"
            title={t("editor.rejectTitle")}
            onClick={reject}
            disabled={!s.asset || busy}
          >
            <Ban className="ico" aria-hidden /> {t("editor.reject")}
          </button>
        </div>
      )}

      {why.length > 0 && (
        <div className="blk">
          <h3>{t("editor.whyTitle")}</h3>
          <div className="why">
            {why.map((w) => (
              <span key={w} className={`chip sm ${isQualityWarning(w) ? "warn" : ""}`}>
                {w}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* a disabled fieldset turns every control inside off at once */}
      <fieldset className="ro stack" disabled={readOnly} style={{ gap: 16 }}>
        <BurstStrip project={p} i={i} onPick={pickBurst} />
        {shot && <CameraSection project={p} shot={shot} i={i} onInfo={onInfo} />}
        <TransitionSection project={p} plan={plan} shot={shot} i={i} mobile={mobile} />
      </fieldset>

      {a && (
        <div className="meta-foot">
          <Calendar className="ico ico-sm" aria-hidden /> {fmtDate(a.date)}
          <span className="spacer" />
          <span className="text-caption">
            {a.video
              ? t("editor.metaVideo", { s: Math.round(a.duration ?? 0) })
              : isPortrait(a)
                ? t("editor.metaPortrait")
                : t("editor.metaLandscape")}
          </span>
        </div>
      )}
    </>
  );

  if (!mobile)
    return (
      <>
        {head}
        <div className="insp-body">{body}</div>
      </>
    );
  return (
    <>
      {head}
      <div className="scroll">
        <div className="insp-body">{body}</div>
      </div>
      {readOnly && (
        // the page's frozen / job bar is under the sheet: say why the buttons are gone
        <div className="sheet-bar ro-note" role="note">
          <Lock className="ico ico-sm" aria-hidden />
          {p.frozen
            ? t("editor.readOnlyFrozen")
            : p.running === "analyze"
              ? t("editor.readOnlyAnalyze")
              : t("editor.readOnlySuggest")}
        </div>
      )}
      {!readOnly && (
        <div className="sheet-bar">
          <button type="button" className="btn soft-primary" onClick={() => onChange(i)}>
            <Images className="ico" aria-hidden />
            {t("editor.change")}
          </button>
          <button type="button" className="btn danger" onClick={reject} disabled={!s.asset || busy}>
            <Ban className="ico" aria-hidden />
            {t("editor.reject")}
          </button>
          <button
            type="button"
            className={`btn ${s.locked ? "selected" : ""}`}
            aria-pressed={!!s.locked}
            onClick={pin}
            disabled={!s.asset || busy}
          >
            <Pin className="ico" aria-hidden />
            {s.locked ? t("editor.pinned") : t("editor.pin")}
          </button>
          <button type="button" className="btn" onClick={() => setMore(true)}>
            <Ellipsis className="ico" aria-hidden />
            {t("editor.more")}
          </button>
        </div>
      )}
      <Dialog open={more} onClose={() => setMore(false)} title={t("shot.title", { n: i + 1 })}>
        <div className="menu" style={{ padding: 0 }}>
          <button
            type="button"
            disabled={!p.history?.undo || blocksEdits(p)}
            onClick={() => {
              setMore(false);
              history.mutate("undo", {
                onSuccess: (r) => toast({ text: t("toasts.undone", { what: r.undone }) }),
                onError: fail,
              });
            }}
          >
            <Undo2 className="ico" />{" "}
            {p.history?.undo ? t("editor.undo", { what: p.history.undo }) : t("editor.nothingToUndo")}
          </button>
          <button
            type="button"
            disabled={!p.history?.redo || blocksEdits(p)}
            onClick={() => {
              setMore(false);
              history.mutate("redo", {
                onSuccess: (r) => toast({ text: t("toasts.redone", { what: r.redone }) }),
                onError: fail,
              });
            }}
          >
            <Redo2 className="ico" />{" "}
            {p.history?.redo ? t("editor.redo", { what: p.history.redo }) : t("editor.nothingToRedo")}
          </button>
          <hr />
          <button type="button" onClick={() => (setMore(false), onExchange(i))} disabled={!s.asset || busy}>
            <ArrowLeftRight className="ico" /> {t("editor.swap")}
          </button>
          <button type="button" onClick={() => (setMore(false), void paste())}>
            <ClipboardPaste className="ico" /> {t("editor.paste")}
          </button>
        </div>
      </Dialog>
    </>
  );
}

function WarningCallout({
  w,
  onChange,
  onGoto,
  onAuto,
  readOnly,
}: {
  w: Warning;
  onChange: () => void;
  onGoto: (i: number) => void;
  onAuto: () => void;
  readOnly?: boolean;
}) {
  const { t } = useTranslation(["storyboard", "terms"]);
  if (w.reviewed)
    return (
      <div className="callout">
        {w.kind === "repeat" ? (
          <Repeat2 className="ico" aria-hidden />
        ) : (
          <TriangleAlert className="ico" aria-hidden />
        )}
        <div>
          {w.text}. <span className="muted">{t("callout.reviewed")}</span>
        </div>
        {w.kind === "repeat" && (
          <button type="button" className="btn sm ghost" onClick={() => onGoto(w.other)}>
            {t("callout.goto", { n: w.other + 1 })} <ArrowRight className="ico ico-sm" aria-hidden />
          </button>
        )}
      </div>
    );
  if (w.kind === "repeat")
    return (
      <div className="callout warn">
        <Repeat2 className="ico" aria-hidden />
        <div>
          <b>{w.text}</b>
        </div>
        <button type="button" className="btn sm ghost" onClick={() => onGoto(w.other)}>
          {t("callout.goto", { n: w.other + 1 })} <ArrowRight className="ico ico-sm" aria-hidden />
        </button>
      </div>
    );
  if (w.kind === "pixelate")
    return (
      <div className="callout danger">
        <ZoomIn className="ico" aria-hidden />
        <div>
          <b>{t("terms:warnings.pixelate")}.</b>
          <br />
          <span className="muted">{t("callout.pixelateHint")}</span>
        </div>
        {!readOnly && (
          <button type="button" className="btn sm danger" onClick={onAuto}>
            {t("callout.setAuto")}
          </button>
        )}
      </div>
    );
  return (
    <div className="callout warn">
      <TriangleAlert className="ico" aria-hidden />
      <div>
        <b>{w.text}.</b>
        {w.kind === "sensitive" && (
          <>
            <br />
            <span className="muted">{t("callout.sensitiveHint")}</span>
          </>
        )}
      </div>
      {!readOnly && (
        <button type="button" className="btn sm warning" onClick={onChange}>
          {w.kind === "empty" ? t("callout.addPhoto") : t("callout.change")}
        </button>
      )}
    </div>
  );
}

function BurstStrip({
  project: p,
  i,
  onPick,
}: {
  project: Project;
  i: number;
  onPick: (id: string) => void;
}) {
  const { t } = useTranslation("storyboard");
  const s = p.slots[i]!;
  const known = (s.burst?.length ?? 0) > 1;
  const { data } = useBurst(p.id, i, s.asset, known);
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // the photo in use may be far along the strip: bring it into view
    const el = strip.current?.querySelector<HTMLElement>(".b.cur");
    if (el && strip.current)
      strip.current.scrollLeft = el.offsetLeft - strip.current.clientWidth / 2 + el.clientWidth / 2;
  }, [data, s.asset]);
  if (!known || !data || data.length < 2) return null;
  return (
    <div className="blk">
      <h3>
        <Film className="ico ico-sm" aria-hidden /> {t("burst.title", { count: data.length })}
      </h3>
      <div className="burst" ref={strip}>
        {data.map((b, k) => {
          const cur = b.id === s.asset;
          const q = b.why.find((w) => /^(😑|💨|〰️)/.test(w))?.slice(0, 2);
          return (
            <button
              key={b.id}
              type="button"
              className={`b ${cur ? "cur" : ""}`}
              aria-label={t(
                cur
                  ? b.best
                    ? "burst.photoInUseBest"
                    : "burst.photoInUse"
                  : b.best
                    ? "burst.photoBest"
                    : "burst.photo",
                { n: k + 1 },
              )}
              aria-pressed={cur}
              onClick={() => !cur && onPick(b.id)}
              title={b.why.join(" · ")}
            >
              <div className="photo frame-43" style={{ backgroundImage: `url(${assetUrl(b.id)})` }} />
              {cur ? (
                <span className="tag">{t("burst.inUse")}</span>
              ) : b.best ? (
                <span className="tag best">{t("burst.best")}</span>
              ) : null}
              {q && <span className="q">{q}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Section({
  icon,
  title,
  summary,
  open,
  children,
}: {
  icon: ReactNode;
  title: string;
  summary: string;
  open: boolean;
  children: ReactNode;
}) {
  return (
    <details className="sect" open={open}>
      <summary>
        <span className="t">
          {icon} {title}
        </span>
        <span className="s truncate">{summary}</span>
        <ChevronDown className="ico chev" aria-hidden />
      </summary>
      <div className="sect-body">{children}</div>
    </details>
  );
}

function CameraSection({
  project: p,
  shot,
  i,
  onInfo,
}: {
  project: Project;
  shot: Shot;
  i: number;
  onInfo: (id: string, slot: number) => void;
}) {
  const { t } = useTranslation("storyboard");
  const act = useShotActions(p.id);
  const toast = useToast();
  const fail = (e: Error) => toast({ text: e.message, tone: "error" });
  const first = shot.slots[0]!;
  const asset = p.slots[first]?.asset ?? undefined;
  const a = asset ? p.assets[asset] : undefined;
  const [pairOpen, setPairOpen] = useState(false);

  if (first !== i)
    return (
      <div className="callout">
        <Images className="ico" aria-hidden />
        <div className="grow">{t("camera.sharesWith", { n: first + 1 })}</div>
        <button
          type="button"
          className="btn sm ghost"
          onClick={() => act.look.mutate({ slot: first, kind: "single" }, { onError: fail })}
        >
          {t("camera.split")}
        </button>
      </div>
    );

  if (shot.kind === "video")
    return (
      <div className="callout">
        <Film className="ico" aria-hidden />
        <div>{t("camera.video")}</div>
      </div>
    );

  const mv = moveState(shot);
  const summary = `${lookLabel(shot)}${["polaroid", "polaroid_pair", "diptych"].includes(shot.kind) ? "" : ` · ${mv.value} %`}`;
  const prints = shot.kind === "polaroid" ? [asset] : shot.kind === "polaroid_pair" ? [asset, shot.pair] : [];
  return (
    <Section
      icon={<Move className="ico ico-sm" aria-hidden />}
      title={t("camera.title")}
      summary={summary}
      open
    >
      <label className="lookbtn" style={{ position: "relative" }}>
        <span className="lic">{LOOK_ICON[shot.kind] ?? <Sparkles className="ico" />}</span>
        <span className="grow">
          <span className="text-caption muted">{t("camera.framing")}</span>
          <br />
          <span className="strong text-small">{lookLabel(shot)}</span>
        </span>
        <ChevronDown className="ico muted" aria-hidden />
        <select
          aria-label={t("camera.framingLabel")}
          value={shot.override ?? ""}
          onChange={(e) => {
            const kind = e.target.value || null;
            act.look.mutate(
              { slot: first, kind },
              {
                onError: fail,
                // a second photo was asked for but the app found none: let the user pick it
                onSuccess: (plan) => {
                  const sh = plan.shots.find((x) => x.slots[0] === first);
                  if ((kind === "diptych_other" || kind === "polaroid_pair") && !sh?.pair) setPairOpen(true);
                },
              },
            );
          }}
          style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer" }}
        >
          <option value="">{t("camera.auto")}</option>
          {lookOptions(a).map((k) => (
            <option key={k} value={k}>
              {lookName(k)}
            </option>
          ))}
          {shot.override && !lookOptions(a).includes(shot.override) && (
            <option value={shot.override}>{lookName(shot.override)}</option>
          )}
        </select>
      </label>

      {shot.pair && (
        <div className="pair">
          <div className="photo" style={{ backgroundImage: `url(${assetUrl(shot.pair)})` }} />
          <div className="grow">
            <div className="strong text-small">{t("camera.secondPhoto")}</div>
            <div className="muted text-caption">
              {t("camera.pairFrom", { from: pairFrom(shot.pair_from) })}
            </div>
          </div>
          <button
            type="button"
            className="icon-btn sm bare"
            aria-label={t("camera.secondPhotoDetails")}
            onClick={() => onInfo(shot.pair!, first)}
          >
            <Info className="ico" />
          </button>
          <button type="button" className="btn sm ghost" onClick={() => setPairOpen(true)}>
            {t("camera.changeSecond")}
          </button>
          <button
            type="button"
            className="icon-btn sm bare"
            aria-label={t("camera.removeSecond")}
            onClick={() => act.look.mutate({ slot: first, kind: "single" }, { onError: fail })}
          >
            <X className="ico" />
          </button>
        </div>
      )}

      {prints.map((id, k) =>
        id ? (
          <CaptionField
            key={`${id}-${shot.captions?.[k] ?? ""}`}
            label={k ? t("camera.captionSecond") : t("camera.captionFirst")}
            value={shot.captions?.[k] ?? ""}
            auto={!!shot.caption_auto?.[k]}
            onSave={(text) => act.caption.mutate({ asset: id, text }, { onError: fail })}
          />
        ) : null,
      )}

      {!["polaroid", "polaroid_pair", "diptych"].includes(shot.kind) && (
        <MoveSlider
          key={first}
          shot={shot}
          onCommit={(factor) => act.move.mutate({ slot: first, factor }, { onError: fail })}
        />
      )}
      <Chooser project={p} i={pairOpen ? first : null} mode="pair" onClose={() => setPairOpen(false)} />
    </Section>
  );
}

function CaptionField({
  label,
  value,
  auto,
  onSave,
}: {
  label: string;
  value: string;
  auto: boolean;
  onSave: (t: string | null) => void;
}) {
  const { t } = useTranslation("storyboard");
  const [text, setText] = useState(value);
  const commit = () => text !== value && onSave(text);
  return (
    <label className="capf">
      <span className="sr-only">{label}</span>
      <Pencil className="ico muted" aria-hidden />
      <input
        className="input"
        value={text}
        maxLength={40}
        placeholder={t("camera.noText")}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
      />
      {auto ? (
        <span className="badge">{t("camera.autoBadge")}</span>
      ) : (
        <button
          type="button"
          className="icon-btn sm bare"
          aria-label={t("camera.backToAutoText")}
          onClick={() => onSave(null)}
        >
          <RotateCcw className="ico" />
        </button>
      )}
    </label>
  );
}

function MoveSlider({ shot, onCommit }: { shot: Shot; onCommit: (f: number | null) => void }) {
  const { t } = useTranslation("storyboard");
  const st = moveState(shot);
  const [v, setV] = useState(st.value);
  // follow changes from outside (undo, «Set to auto») without remounting, which would lose the keyboard focus
  const [seen, setSeen] = useState(st.value);
  if (st.value !== seen) {
    setSeen(st.value);
    setV(st.value);
  }
  const pos = (x: number) => `${(Math.min(150, x) / 150) * 100}%`;
  const track = `linear-gradient(90deg, var(--color-zone-ok) 0 ${pos(st.yellow)}, var(--color-zone-warn) ${pos(st.yellow)} ${pos(st.red)}, var(--color-zone-bad) ${pos(st.red)} 100%)`;
  const zone = v > st.red ? "red" : v > st.yellow ? "yellow" : "green";
  // read the control itself: the state may not have caught up yet when the key or pointer is released
  const commit = (x: number) => x !== st.value && onCommit(x / 100);
  return (
    <div className="field">
      <div className="row">
        <span className="label strong text-small">{t("move.title")}</span>
        <span className="spacer" />
        {st.auto ? (
          <span className="badge">{t("move.auto")}</span>
        ) : (
          <button type="button" className="btn xs ghost" onClick={() => onCommit(null)}>
            <RotateCcw className="ico ico-sm" aria-hidden /> {t("move.auto")}
          </button>
        )}
      </div>
      <div className="mv-row">
        <input
          className="mv-range"
          type="range"
          min={0}
          max={150}
          step={5}
          value={v}
          style={{ ["--track" as string]: track }}
          aria-label={t("move.label")}
          aria-valuetext={`${v} %`}
          onChange={(e) => setV(+e.target.value)}
          onPointerUp={(e) => commit(+e.currentTarget.value)}
          onKeyUp={(e) => commit(+e.currentTarget.value)}
        />
        <span className="mv-val">{v} %</span>
      </div>
      <div className="mv-scale" style={{ position: "relative", height: 14, marginRight: 58 }}>
        <span style={{ position: "absolute", left: 0 }}>{t("move.still")}</span>
        <span style={{ position: "absolute", left: "66.6%", transform: "translateX(-50%)" }}>100 %</span>
        <span style={{ position: "absolute", right: 0 }}>150 %</span>
      </div>
      {zone === "red" ? (
        <span className="zone danger-text">
          <i style={{ background: "var(--color-danger-solid)" }} />
          {t("move.red")}
        </span>
      ) : zone === "yellow" ? (
        <span className="zone warn-text">
          <i style={{ background: "var(--color-warn-solid)" }} />
          {t("move.yellow")}
        </span>
      ) : (
        <span className="zone ok-text">
          <i style={{ background: "var(--color-ok-solid)" }} />
          {st.autoLimited && v === st.value ? t("move.autoMax") : t("move.ok")}
        </span>
      )}
    </div>
  );
}

function TransitionSection({
  project: p,
  plan,
  shot,
  i,
  mobile,
}: {
  project: Project;
  plan: Plan | undefined;
  shot: Shot | undefined;
  i: number;
  mobile: boolean;
}) {
  const { t } = useTranslation(["storyboard", "terms"]);
  const act = useShotActions(p.id);
  const toast = useToast();
  const last = shot ? shot.slots.at(-1)! : i;
  if (last >= p.slots.length - 1) return null;
  const inner = plan?.inner?.find((b) => b.after_slot === i);
  if (inner?.kind === "diptych" || (shot && shot.slots.length > 1 && i !== last))
    return <div className="muted text-small">{t("transition.diptychNext")}</div>;
  const b: Boundary | undefined = plan?.boundaries.find((x) => x.after_slot === last);
  if (!b) return null;
  const name = transitionName(b.kind);
  const beats =
    b.kind !== "cut" && b.kind !== "flash" && b.beats
      ? ` · ${t("transition.beats", { count: b.beats })}`
      : "";
  return (
    <Section
      icon={<Shuffle className="ico ico-sm" aria-hidden />}
      title={t("transition.title", { n: last + 2 })}
      summary={b.override ? name : t("terms:auto", { name })}
      open={!mobile}
    >
      <select
        className="select"
        aria-label={t("transition.label")}
        value={b.override ? b.kind : ""}
        onChange={(e) =>
          act.transition.mutate(
            { after: last, kind: e.target.value || null },
            { onError: (er) => toast({ text: er.message, tone: "error" }) },
          )
        }
      >
        <option value="">{t("terms:auto", { name: transitionName(b.auto ?? b.kind) })}</option>
        {transitions().map(([k, n]) => (
          <option key={k} value={k}>
            {n}
          </option>
        ))}
      </select>
      <div className="muted text-small">
        {name}
        {beats}
        {b.reason ? ` · ${b.reason}` : ""}
      </div>
    </Section>
  );
}

export function SnippetDialog({
  open,
  onClose,
  project: p,
  i,
}: {
  open: boolean;
  onClose: () => void;
  project: Project;
  i: number;
}) {
  const { t } = useTranslation("storyboard");
  // made again whenever the project changed (edit_rev); kept a minute for reopening
  const q = useQuery({
    queryKey: ["snippet", p.id, i, p.edit_rev ?? 0, p.title_overlay, p.subtitles],
    queryFn: () => makeSnippet(p.id, i),
    enabled: open,
    staleTime: 60_000,
    gcTime: 60_000,
    retry: false,
    refetchOnWindowFocus: false, // it runs ffmpeg: never again just for coming back to the tab
  });
  return (
    <Dialog open={open} onClose={onClose} title={t("shot.title", { n: i + 1 })} wide>
      {q.data ? (
        <video
          src={`/api/projects/${p.id}/files/${q.data.file}`}
          controls
          autoPlay
          playsInline
          style={{ width: "100%", borderRadius: 8, background: "var(--color-stage)" }}
        />
      ) : q.error ? (
        <p className="danger-text">{t("snippet.failed", { error: q.error.message })}</p>
      ) : (
        <p className="muted">{t("snippet.making")}</p>
      )}
    </Dialog>
  );
}
