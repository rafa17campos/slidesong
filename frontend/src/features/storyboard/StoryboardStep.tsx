import { Captions, Film, Keyboard, LayoutGrid, Pin, Rows3, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useSearchParams } from "react-router";

import { useUndoToast } from "@/hooks/useUndoToast";
import type { Plan, Project } from "@/api/types";
import { Dialog } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { shortcutHelp, useShortcuts } from "@/hooks/useShortcuts";
import { energy, SECTION_COLOR, sectionName } from "@/lib/names";
import {
  fmtTime,
  groupBySection,
  matches,
  shotBySlot,
  warningsFor,
  type Filter,
  open as openWarnings,
} from "@/lib/storyboard";

import { useShotActions } from "./actions";
import { Chooser } from "./Chooser";
import { PhotoSheet, type SheetTarget } from "./PhotoSheet";
import { ShotEditor, SnippetDialog } from "./ShotEditor";
import { ShotTile } from "./ShotTile";
import { SongMap } from "./SongMap";

const FILTERS: { id: Filter; icon?: React.ReactNode }[] = [
  { id: "all" },
  { id: "warnings", icon: <TriangleAlert className="ico ico-sm warn-text" aria-hidden /> },
  { id: "pinned", icon: <Pin className="ico ico-sm" aria-hidden /> },
  { id: "videos", icon: <Film className="ico ico-sm" aria-hidden /> },
  { id: "subs", icon: <Captions className="ico ico-sm" aria-hidden /> },
];

function storedDense() {
  try {
    return localStorage.getItem("slidesong:dense") === "1";
  } catch {
    return false;
  }
}

/** ③ Storyboard: the storyboard grouped by song section, and the shot editor (side panel / full-screen sheet). */
export function StoryboardStep({
  project: p,
  plan,
  readOnly = false,
}: {
  project: Project;
  plan: Plan | undefined;
  readOnly?: boolean;
}) {
  const { t } = useTranslation(["storyboard", "common"]);
  const wide = useMediaQuery("(min-width: 1024px)");
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const act = useShotActions(p.id);
  const undoToast = useUndoToast(p.id);
  // ?review=1 (from ④ Video): start the warnings walk
  const [filter, setFilter] = useState<Filter>(() => (params.has("review") ? "warnings" : "all"));
  const [dense, setDense] = useState(storedDense);
  const [changeFor, setChangeFor] = useState<number | null>(null);
  const [snipFor, setSnipFor] = useState<number | null>(null);
  const [help, setHelp] = useState(false);
  const [sheet, setSheet] = useState<SheetTarget | null>(null);

  const n = p.slots.length;
  const groups = useMemo(() => groupBySection(p, plan), [p, plan]);
  const shots = useMemo(() => shotBySlot(plan), [plan]);
  const warns = useMemo(() => p.slots.map((_, i) => warningsFor(p, plan, i)), [p, plan]);
  const warned = useMemo(() => warns.flatMap((w, i) => (openWarnings(w).length ? [i] : [])), [warns]);
  const counts = useMemo(
    () =>
      Object.fromEntries(
        FILTERS.map((f) => [f.id, p.slots.filter((_, i) => matches(p, plan, i, f.id)).length]),
      ),
    [p, plan],
  ) as Record<Filter, number>;

  // the open shot lives in the URL (?shot=12): shareable, and Android's back button closes the sheet
  const param = Number(params.get("shot"));
  const fromUrl = param >= 1 && param <= n ? param - 1 : null;
  const current = fromUrl ?? (wide && n ? (warned[0] ?? 0) : null);
  const sheetOpen = !wide && fromUrl != null;
  // phones: while the shot sheet is open, the page behind it is out of reach (focus and screen readers)
  useEffect(() => {
    if (!sheetOpen) return;
    const behind = [...document.querySelectorAll<HTMLElement>(".phead, .mj")];
    behind.forEach((el) => (el.inert = true));
    document.querySelector<HTMLElement>(".sheet .insp-head h2")?.focus();
    return () => behind.forEach((el) => (el.inert = false));
  }, [sheetOpen, current]);
  // the sheet closed: focus goes back to the shot it was about (not to the top of the page)
  const sheetFor = useRef<number | null>(null);
  useEffect(() => {
    if (sheetOpen) {
      sheetFor.current = current;
      return;
    }
    const i = sheetFor.current;
    sheetFor.current = null;
    if (i != null)
      requestAnimationFrame(() => document.querySelector<HTMLElement>(`.tile[data-i="${i}"]`)?.focus());
  }, [sheetOpen, current]);
  // desktop: the shot shown by default goes into the URL, so fixing its warning does not jump elsewhere
  useEffect(() => {
    if (wide && fromUrl == null && current != null && plan) {
      const next = new URLSearchParams(params);
      next.set("shot", String(current + 1));
      setParams(next, { replace: true });
    }
  }, [wide, fromUrl, current, params, setParams, plan]);
  // ?review=1: open the first warning once the plan (which the warnings come from) is there
  useEffect(() => {
    if (!params.has("review") || !plan) return;
    const next = new URLSearchParams(params);
    next.delete("review");
    setParams(next, { replace: true });
    if (!warned.length) return;
    next.set("shot", String(warned[0]! + 1));
    // phones: one more history entry, so back closes the sheet onto the shots (as when opening one by hand)
    setParams(next, wide ? { replace: true } : { state: { sheet: true } });
  }, [params, plan, warned, wide, setParams]);
  // «Swap» mode lives in the URL too (?swap=12), so the back button cancels it
  const xParam = Number(params.get("swap"));
  const xFrom = xParam >= 1 && xParam <= n ? xParam - 1 : null;
  const location = useLocation();
  const pushed = !!(location.state as { sheet?: boolean } | null)?.sheet;

  // Opening a shot on a phone pushes a history entry marked {sheet}: closing it (✕ or back) returns to the
  // storyboard. Other changes replace the entry and keep that mark.
  const open = useCallback(
    (i: number, how: "push" | "replace" = wide ? "replace" : "push") => {
      const next = new URLSearchParams(params);
      next.set("shot", String(i + 1));
      next.delete("swap");
      if (how === "push") setParams(next, { state: { sheet: true } });
      else setParams(next, { replace: true, state: location.state });
      requestAnimationFrame(() =>
        document
          .querySelector(`.tile[data-i="${i}"]`)
          ?.scrollIntoView({ block: "nearest", behavior: "smooth" }),
      );
    },
    [params, setParams, wide, location.state],
  );
  const close = () => {
    if (pushed) navigate(-1);
    else {
      const next = new URLSearchParams(params);
      next.delete("shot");
      setParams(next, { replace: true });
    }
  };
  const startExchange = (i: number) => {
    const next = new URLSearchParams(params);
    next.set("swap", String(i + 1));
    if (!wide) next.delete("shot"); // phones: back to the storyboard to pick the other shot
    setParams(next, { replace: true, state: location.state });
  };
  const cancelExchange = () => {
    const next = new URLSearchParams(params);
    next.delete("swap");
    setParams(next, { replace: true, state: location.state });
  };
  // ‹ › walk the shots shown by the filter (with "Con aviso": only the warnings)
  const visible = useMemo(
    () => p.slots.map((_, i) => i).filter((i) => matches(p, plan, i, filter)),
    [p, plan, filter],
  );
  // with «With warnings» (the «Review warnings» walk), ‹ › go to the previous / next warning, even after the
  // current one has been fixed and left the list
  const neighbour = (d: -1 | 1): number | null => {
    if (current == null) return null;
    if (filter === "warnings")
      return (
        (d > 0 ? warned.find((i) => i > current) : [...warned].reverse().find((i) => i < current)) ?? null
      );
    const list = visible.includes(current) ? visible : p.slots.map((_, i) => i);
    const next = list[list.indexOf(current) + d];
    return next ?? null;
  };
  const step = (d: -1 | 1) => {
    const next = neighbour(d);
    if (next != null) open(next, "replace");
  };
  const counter =
    filter === "warnings" && current != null && warned.includes(current)
      ? t("board.counter", { n: warned.indexOf(current) + 1, total: warned.length })
      : null;

  const exchange = (b: number) => {
    const a = xFrom!;
    if (a === b) return cancelExchange();
    act.exchange.mutate(
      { a, b },
      {
        onSuccess: (r) => {
          undoToast(t("swap.done", { a: a + 1, b: b + 1 }), r);
          open(b, "replace");
        },
        onError: (e) => toast({ text: e.message, tone: "error" }),
      },
    );
  };
  const pick = (i: number) => (xFrom != null ? exchange(i) : open(i));

  const cur = current != null ? p.slots[current] : undefined;
  useShortcuts(
    {
      arrowleft: () => step(-1),
      arrowright: () => step(1),
      k: () => step(-1),
      j: () => step(1),
      escape: () => (xFrom != null ? cancelExchange() : sheetOpen ? close() : undefined),
      c: () => !readOnly && current != null && setChangeFor(current),
      p: () => current != null && cur?.asset && setSnipFor(current),
      f: () =>
        !readOnly &&
        !act.slot.isPending &&
        current != null &&
        cur?.asset &&
        act.slot.mutate(
          { i: current, change: { action: cur.locked ? "unlock" : "lock" } },
          { onError: (e) => toast({ text: e.message, tone: "error" }) },
        ),
      x: () =>
        !readOnly &&
        !act.slot.isPending &&
        current != null &&
        cur?.asset &&
        act.slot.mutate(
          { i: current, change: { action: "reject" } },
          {
            onSuccess: (r) => undoToast(t("toasts.rejected", { n: current + 1 }), r),
            onError: (e) => toast({ text: e.message, tone: "error" }),
          },
        ),
      "?": () => setHelp(true),
    },
    changeFor == null && snipFor == null && !help && !sheet,
  );

  useEffect(() => {
    try {
      localStorage.setItem("slidesong:dense", dense ? "1" : "0");
    } catch {
      /* not remembered */
    }
  }, [dense]);

  if (!n)
    return (
      <main className="page">
        <p className="muted">{t("board.noShots")}</p>
      </main>
    );

  const editor =
    current != null ? (
      <ShotEditor
        key={current}
        project={p}
        plan={plan}
        i={current}
        shot={shots.get(current)}
        group={groups.find((g) => g.slots.includes(current))}
        warnings={warns[current] ?? []}
        mobile={!wide}
        onStep={step}
        onClose={close}
        onGoto={(i) => open(i, "replace")}
        onExchange={startExchange}
        counter={counter}
        hasPrev={neighbour(-1) != null}
        hasNext={neighbour(1) != null}
        onChange={setChangeFor}
        onSnippet={setSnipFor}
        readOnly={readOnly}
        onInfo={(id, slot) => setSheet({ id, slot })}
      />
    ) : null;

  return (
    <>
      {xFrom != null && (
        <div className="xchg-bar" role="status">
          {t("swap.bar", { n: xFrom + 1 })}
          <button type="button" className="btn sm" onClick={cancelExchange}>
            {t("common:actions.cancel")}
          </button>
        </div>
      )}
      <div className={`mj ${dense ? "dense" : ""} ${xFrom != null ? "xmode" : ""}`}>
        <section className="board" aria-label={t("board.label")}>
          <div className="board-bar">
            <SongMap
              project={p}
              groups={groups}
              warned={warned}
              current={current}
              onSection={(g) =>
                document.getElementById(`sec-${g}`)?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            />
            <div className="filters">
              <div className="seg" role="group" aria-label={t("filters.label")}>
                {FILTERS.map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    aria-pressed={filter === f.id}
                    onClick={() => setFilter(f.id)}
                  >
                    {f.icon}
                    {t(`filters.${f.id}`)} <span className="cnt">{counts[f.id]}</span>
                  </button>
                ))}
              </div>
              <span className="spacer hide-mobile" />
              {warned.length > 0 && !p.frozen && (
                <button
                  type="button"
                  className="btn sm warning"
                  style={{ flex: "none" }}
                  onClick={() => {
                    setFilter("warnings");
                    open(warned[0]!);
                  }}
                >
                  <TriangleAlert className="ico ico-sm" aria-hidden />
                  {t("board.reviewWarnings")}
                </button>
              )}
              <div className="seg" role="group" aria-label={t("size.label")} style={{ flex: "none" }}>
                <button
                  type="button"
                  aria-pressed={!dense}
                  aria-label={t("size.cards")}
                  onClick={() => setDense(false)}
                >
                  <Rows3 className="ico ico-sm" />
                </button>
                <button
                  type="button"
                  aria-pressed={dense}
                  aria-label={t("size.dense")}
                  onClick={() => setDense(true)}
                >
                  <LayoutGrid className="ico ico-sm" />
                </button>
              </div>
              {wide && (
                <button
                  type="button"
                  className="icon-btn sm bare"
                  aria-label={t("shortcuts.title")}
                  title={t("shortcuts.button")}
                  onClick={() => setHelp(true)}
                >
                  <Keyboard className="ico" />
                </button>
              )}
            </div>
          </div>

          {counts[filter] === 0 && <p className="grp-empty">{t(`empty.${filter}`)}</p>}
          {groups.map((g, k) => {
            const slots = g.slots.filter((i) => matches(p, plan, i, filter));
            if (!slots.length) return null;
            const sec = g.section;
            return (
              <section key={k} className="grp" id={`sec-${k}`}>
                <div className="grp-h">
                  <span
                    className="sec-pill"
                    style={{ ["--c" as string]: SECTION_COLOR[sec?.kind ?? "verse"] }}
                  >
                    {sectionName(sec)}
                  </span>
                  <span className="muted tnum">
                    {fmtTime(g.from)} – {fmtTime(g.to)}
                  </span>
                  <span className="subtle hide-mobile">
                    {sec?.mood ? `· ${energy(sec.mood)} ` : ""}· {t("board.shots", { count: g.slots.length })}
                  </span>
                </div>
                <div className="sb-grid">
                  {slots.map((i) => (
                    <ShotTile
                      key={i}
                      project={p}
                      shot={shots.get(i)}
                      i={i}
                      warnings={warns[i] ?? []}
                      current={wide && i === current}
                      xsrc={i === xFrom}
                      onPick={pick}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </section>
        {wide && (
          <aside className="insp" aria-label={t("board.selected")}>
            {editor}
          </aside>
        )}
      </div>

      {sheetOpen && (
        <div
          className="sheet"
          role="dialog"
          aria-modal="true"
          aria-label={t("board.editShot", { n: current! + 1 })}
        >
          {editor}
        </div>
      )}

      <Chooser
        project={p}
        i={changeFor}
        mode="change"
        group={changeFor != null ? groups.find((g) => g.slots.includes(changeFor)) : undefined}
        onClose={() => setChangeFor(null)}
        onInfo={(id, slot) => setSheet({ id, slot })}
      />
      <PhotoSheet project={p} plan={plan} target={sheet} onClose={() => setSheet(null)} readOnly={readOnly} />
      <SnippetDialog open={snipFor != null} onClose={() => setSnipFor(null)} project={p} i={snipFor ?? 0} />
      <Dialog open={help} onClose={() => setHelp(false)} title={t("shortcuts.title")}>
        <table className="text-small" style={{ width: "100%", borderSpacing: "0 8px" }}>
          <tbody>
            {shortcutHelp().map(([k, d]) => (
              <tr key={k}>
                <td style={{ whiteSpace: "nowrap", paddingRight: 16 }}>
                  <span className="kbd">{k}</span>
                </td>
                <td className="secondary">{d}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Dialog>
    </>
  );
}
