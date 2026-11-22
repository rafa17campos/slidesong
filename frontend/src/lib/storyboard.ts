// What the storyboard and the shot editor show, derived from the project and its plan (no UI here).
import type { Plan, PlanSection, Project, Shot } from "@/api/types";

import i18n from "@/i18n";

import { sectionKindName } from "./names";

export interface Group {
  section: PlanSection | null;
  from: number; // seconds
  to: number;
  slots: number[];
}

/** Shots grouped by song section (one group when the plan has no sections yet). */
export function groupBySection(p: Project, plan: Plan | undefined): Group[] {
  const n = p.slots.length;
  if (!n) return [];
  const secs = [...(plan?.sections ?? [])].filter((s) => s.slot < n).sort((a, b) => a.slot - b.slot);
  const starts = secs.length ? secs : [null];
  return starts.map((sec, k) => {
    const first = k === 0 ? 0 : sec!.slot;
    const next = starts[k + 1];
    const last = next ? next.slot - 1 : n - 1;
    const slots = Array.from({ length: last - first + 1 }, (_, j) => first + j);
    return { section: sec, from: p.slots[first]!.start, to: p.slots[last]!.end, slots };
  });
}

/** slot index -> the shot that shows it (a diptych or two prints can cover two slots). */
export function shotBySlot(plan: Plan | undefined): Map<number, Shot> {
  const m = new Map<number, Shot>();
  for (const sh of plan?.shots ?? []) for (const i of sh.slots) m.set(i, sh);
  return m;
}

// ---------------- warnings ----------------

export type Warning = (
  | { kind: "empty"; text: string }
  | { kind: "sensitive"; text: string }
  | { kind: "repeat"; text: string; other: number; sim?: number }
  | { kind: "pixelate"; text: string }
) & {
  /** the photo is pinned: the user has looked at it and kept it, so the warning no longer counts */
  reviewed?: boolean;
};

/** The "⚠️ ..." tag the suggestion put on a sensitive photo (swimwear, shirtless...), without the icon. */
export function sensitiveTag(p: Project, i: number): string | null {
  const s = p.slots[i];
  const tag = s?.asset ? s.why?.[s.asset]?.find((t) => t.startsWith("⚠️")) : undefined;
  return tag ? tag.replace(/^⚠️\s*/, "") : null;
}

export type Zone = "green" | "yellow" | "red";

/** The camera-move value shown on the slider (in %), and the zone it falls in. */
export function moveState(sh: Shot) {
  const auto = sh.move == null;
  const value = auto ? (sh.res_limited ? (sh.auto_pct ?? 100) : 100) : Math.round(sh.move! * 100);
  const yellow = sh.zones?.[0] ?? 150;
  const red = sh.zones?.[1] ?? 150;
  const zone: Zone = value > red ? "red" : value > yellow ? "yellow" : "green";
  return { auto, value, yellow, red, zone, autoLimited: auto && !!sh.res_limited };
}

export function warningsFor(p: Project, plan: Plan | undefined, i: number): Warning[] {
  const s = p.slots[i];
  if (!s) return [];
  if (!s.asset) return [{ kind: "empty", text: i18n.t("terms:warnings.empty") }];
  const out: Warning[] = [];
  const tag = sensitiveTag(p, i);
  const kept = !!s.locked;
  if (tag)
    out.push({
      kind: "sensitive",
      text: i18n.t("terms:warnings.sensitive", { tag }),
      ...(kept && { reviewed: true }),
    });
  for (const r of plan?.repeats ?? []) {
    const other = r.a === i ? r.b : r.b === i ? r.a : null;
    if (other == null) continue;
    const pct = r.sim != null ? ` (${Math.round(r.sim * 100)} %)` : "";
    out.push({
      kind: "repeat",
      text: `${i18n.t(`terms:warnings.repeat.${r.kind}`, { n: other + 1 })}${pct}`,
      other,
      sim: r.sim,
      ...(kept && { reviewed: true }),
    });
  }
  const sh = shotBySlot(plan).get(i);
  if (sh && sh.kind !== "video" && sh.slots[0] === i && moveState(sh).zone === "red")
    out.push({ kind: "pixelate", text: i18n.t("terms:warnings.pixelate") });
  return out;
}

export const open = (ws: Warning[]) => ws.filter((w) => !w.reviewed);

/** Slots with at least one warning still to review, in order (for the filter and "Revisar avisos"). */
export function slotsWithWarnings(p: Project, plan: Plan | undefined): number[] {
  return p.slots.map((_, i) => i).filter((i) => open(warningsFor(p, plan, i)).length > 0);
}

// ---------------- filters ----------------

export type Filter = "all" | "warnings" | "pinned" | "videos" | "subs";

export function matches(p: Project, plan: Plan | undefined, i: number, f: Filter): boolean {
  const s = p.slots[i]!;
  switch (f) {
    case "all":
      return true;
    case "warnings":
      return open(warningsFor(p, plan, i)).length > 0;
    case "pinned":
      return !!s.locked;
    case "videos":
      return !!(s.asset && p.assets[s.asset]?.video);
    case "subs":
      return (s.line_idx ?? []).some((k) => p.lines[k]?.sub);
  }
}

export const fmtTime = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

/** The song's sections from its synced lyrics (for the song step, before there is a plan). */
export function sectionsFromLines(p: Project): { group: Group; lines: number[] }[] {
  const out: { group: Group; lines: number[] }[] = [];
  const dur = p.song?.duration ?? p.lines.at(-1)?.end ?? 0;
  p.lines.forEach((l, k) => {
    const key = l.section ? `${l.section.kind}|${l.section.label}` : "";
    const last = out.at(-1);
    if (
      last &&
      (last.group.section ? `${last.group.section.kind}|${last.group.section.label}` : "") === key
    ) {
      last.lines.push(k);
      return;
    }
    const sec = l.section
      ? {
          slot: -1,
          kind: l.section.kind,
          name: sectionKindName(l.section.kind),
          label: l.section.label,
          mood: l.section.mood as "low" | "mid" | "high" | undefined,
        }
      : null;
    out.push({ group: { section: sec, from: k === 0 ? 0 : l.start, to: dur, slots: [] }, lines: [k] });
  });
  out.forEach((x, n) => {
    const next = out[n + 1];
    if (next) x.group.to = next.group.from;
  });
  return out;
}

/** Shots that show each lyric line. */
export function shotsOfLines(p: Project): Map<number, number[]> {
  const m = new Map<number, number[]>();
  p.slots.forEach((s, i) => (s.line_idx ?? []).forEach((k) => m.set(k, [...(m.get(k) ?? []), i])));
  return m;
}
