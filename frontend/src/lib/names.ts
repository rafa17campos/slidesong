// Names for what the planner returns (slidesong/plan.py), in the interface language, and which camera moves fit
// a photo.
import type { Asset, Shot } from "@/api/types";
import i18n from "@/i18n";

const TRANSITION_IDS = [
  "cut",
  "fade",
  "push",
  "slide",
  "wipe",
  "whip",
  "iris",
  "blur",
  "light",
  "dipwhite",
  "dipblack",
  "flash",
  "zoom",
] as const;
type TransitionId = (typeof TRANSITION_IDS)[number] | "diptych";

/** The transitions that can be chosen by hand, with their names: [id, name]. */
export const transitions = (): [string, string][] => TRANSITION_IDS.map((k) => [k, transitionName(k)]);

export const transitionName = (k: string): string =>
  i18n.exists(`terms:transitions.${k}`) ? i18n.t(`terms:transitions.${k as TransitionId}`) : k;

type LookId = keyof (typeof import("@/i18n/locales/en/terms.json"))["looks"];

/** What each shot kind looks like, as the shot editor names it. */
export const lookName = (k: string): string =>
  i18n.exists(`terms:looks.${k}`) ? i18n.t(`terms:looks.${k as LookId}`) : k;

export const isPortrait = (a: Asset | undefined) => {
  if (!a) return false;
  const r = a.aspect ?? (a.w && a.h ? a.w / a.h : 1.5);
  return r < 0.95;
};

/** The camera moves a photo admits (portrait photos also get the layouts with a second photo). */
export function lookOptions(a: Asset | undefined): string[] {
  return isPortrait(a)
    ? [
        "tilt",
        "whole_to_face",
        "face_to_whole",
        "contain_in",
        "contain_out",
        "polaroid",
        "polaroid_pair",
        "diptych_next",
        "diptych_other",
        "in",
        "out",
        "single",
      ]
    : ["in", "out", "pan_lr", "pan_rl", "contain_in", "contain_out"];
}

/** "Automatic: from the face to whole" or the chosen look. */
export function lookLabel(sh: Shot): string {
  const kind = sh.kind === "diptych" && sh.pair ? "diptych_other" : sh.kind;
  const name = lookName(kind);
  return sh.override
    ? name
    : i18n.t("terms:auto", { name: `${name.charAt(0).toLowerCase()}${name.slice(1)}` });
}

/** Where the second photo comes from: "chosen by you", "from the same day"… */
export const pairFrom = (k: string | null | undefined): string =>
  k === "chosen" || k === "day" || k === "burst" ? i18n.t(`terms:pairFrom.${k}`) : "";

export const SECTION_COLOR: Record<string, string> = {
  intro: "var(--color-sec-intro)",
  verse: "var(--color-sec-verse)",
  prechorus: "var(--color-sec-verse)",
  chorus: "var(--color-sec-chorus)",
  bridge: "var(--color-sec-bridge)",
  interlude: "var(--color-sec-intro)",
  outro: "var(--color-sec-outro)",
};

/** "high energy" for a section's mood. */
export const energy = (mood: string | null | undefined): string =>
  mood === "low" || mood === "mid" || mood === "high"
    ? i18n.t("terms:energy", { level: i18n.t(`terms:mood.${mood}`) })
    : "";

/** Quality hints the suggestion writes as "why" tags, shown in amber. */
export const isQualityWarning = (tag: string) => /^(⚠️|😑|💨|〰️|🚫)/.test(tag);

/** The name of a section kind (verse, chorus…). */
export const sectionKindName = (kind: string): string =>
  i18n.exists(`terms:sections.${kind}`)
    ? i18n.t(`terms:sections.${kind as keyof (typeof import("@/i18n/locales/en/terms.json"))["sections"]}`)
    : kind;

/** "Verse 2" when Suno's tag numbers it ("Verse 2 – Acoustic guitars…"); "Song" outside any section. */
export function sectionName(sec: { kind?: string; name: string; label?: string } | null | undefined): string {
  if (!sec) return i18n.t("terms:sections.song");
  const n = sec.label?.split(/[–-]/)[0]?.match(/\d+/)?.[0];
  const name = sec.kind ? sectionKindName(sec.kind) : sec.name;
  return n ? `${name} ${n}` : name;
}
