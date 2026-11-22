import type { Level } from "@/api/types";
import i18n from "@/i18n";

type SignalKey = keyof (typeof import("@/i18n/locales/en/learning.json"))["signals"];
type GroupId = keyof (typeof import("@/i18n/locales/en/learning.json"))["groups"];

/** The signals that score a photo for a shot (suggest.py DEFAULT_WEIGHTS), in words. */
export interface SignalText {
  name: string;
  help: string;
  /** it pushes photos down: «More» avoids them more */
  penalty?: boolean;
}

export const SIGNAL_GROUPS: { id: GroupId; keys: SignalKey[] }[] = [
  { id: "photo", keys: ["aesthetic", "smile", "face", "frontal", "fav", "eyes_closed", "blurry", "quality"] },
  { id: "lyrics", keys: ["lyric", "concept", "tag", "person", "place", "month", "season"] },
  { id: "project", keys: ["theme", "album", "stranger", "video"] },
];

/** «What the photo is like»… in the interface language. */
export const signalGroupTitle = (id: GroupId) => i18n.t(`learning:groups.${id}`);

/** Every signal; the text is looked up with signalText(). */
export const SIGNALS: Record<SignalKey, { penalty?: boolean }> = {
  aesthetic: {},
  smile: {},
  face: {},
  frontal: {},
  fav: {},
  eyes_closed: { penalty: true },
  blurry: { penalty: true },
  quality: { penalty: true },
  lyric: {},
  concept: {},
  tag: {},
  person: {},
  place: {},
  month: {},
  season: {},
  theme: {},
  album: {},
  stranger: { penalty: true },
  video: {},
};

export const isSignal = (k: string): k is SignalKey => k in SIGNALS;

/** A signal's name and help in the interface language. */
export const signalText = (key: SignalKey): SignalText => ({
  name: i18n.t(`learning:signals.${key}.name`),
  help: i18n.t(`learning:signals.${key}.help`),
  penalty: SIGNALS[key].penalty,
});

const LEVEL_KEY = { [-2]: "none", [-1]: "less", 0: "normal", 1: "more", 2: "muchMore" } as const;

export const LEVELS: Level[] = [-2, -1, 0, 1, 2];

/** «None», «Less», «Normal», «More», «Much more» */
export const levelLabel = (level: Level) => i18n.t(`learning:levels.${LEVEL_KEY[level]}`);

/** suggest.LEVELS */
export const LEVEL_FACTOR: Record<Level, number> = { [-2]: 0, [-1]: 0.5, 0: 1, 1: 1.75, 2: 3 };

/**
 * What learning makes of a signal, against its default: «+30 %», «−20 %», or null when it barely moves
 * (or there is nothing learned yet).
 */
export function learnedChange(def: number, learned: number | null | undefined): number | null {
  if (learned == null || !def) return null;
  const r = learned / def - 1;
  return Math.abs(r) < 0.1 ? null : r;
}

/** «+30%» («+30 %» in Spanish) */
export const pct = (r: number) =>
  i18n.t("learning:percentChange", { sign: r > 0 ? "+" : "−", n: Math.round(Math.abs(r) * 100) });

/** The signals that count more and less (names) from what learning changed most. */
export function learnedSummary(signals: { key: string; default: number; learned: number | null }[]) {
  const moved = signals
    .map((s) => ({ key: s.key, r: learnedChange(s.default, s.learned) }))
    .filter((x): x is { key: SignalKey; r: number } => x.r != null && isSignal(x.key))
    .sort((a, b) => Math.abs(b.r) - Math.abs(a.r));
  const name = (k: SignalKey) => signalText(k).name;
  return {
    more: moved
      .filter((x) => x.r > 0)
      .slice(0, 4)
      .map((x) => name(x.key)),
    less: moved
      .filter((x) => x.r < 0)
      .slice(0, 4)
      .map((x) => name(x.key)),
  };
}
