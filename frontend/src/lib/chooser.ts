// Sorting and filtering the photos of "Change photo" (client side, like the old page).
import type { Candidate } from "@/api/types";
import i18n from "@/i18n";

export type Sort = "fit" | "query" | "quality" | "near" | "new" | "old";
export const sortName = (s: Sort): string => i18n.t(`chooser:sort.${s}`);

export interface Show {
  hideUsed: boolean;
  hideSensitive: boolean;
  onlyFav: boolean;
  shape: "all" | "portrait" | "landscape";
  type: "all" | "photo" | "video";
}
export const DEFAULT_SHOW: Show = {
  hideUsed: true,
  hideSensitive: false,
  onlyFav: false,
  shape: "all",
  type: "all",
};

const KEY: Record<Sort, (x: Candidate) => number> = {
  fit: (x) => -(x.fit ?? -99),
  query: (x) => x.rank ?? 0,
  quality: (x) => -(x.quality ?? -99),
  near: (x) => x.days ?? 1e9,
  new: (x) => -Date.parse(x.date ?? "1970-01-01"),
  old: (x) => Date.parse(x.date ?? "2999-01-01"),
};

export function passes(x: Candidate, s: Show): boolean {
  if (s.hideUsed && x.used) return false;
  if (s.hideSensitive && x.sensitive) return false;
  if (s.onlyFav && !x.fav) return false;
  if (s.shape === "portrait" && !x.portrait) return false;
  if (s.shape === "landscape" && !x.landscape) return false;
  if (s.type === "photo" && x.video) return false;
  if (s.type === "video" && !x.video) return false;
  return true;
}

/** The photos to show, in order, and how many the filters hide. */
export function chooserView(items: Candidate[], sort: Sort, show: Show) {
  const key = KEY[sort];
  const visible = items
    .map((x, n) => ({ ...x, rank: x.rank ?? n }))
    .filter((x) => passes(x, show))
    .sort((a, b) => key(a) - key(b) || a.rank - b.rank);
  return { visible, hidden: items.length - visible.length };
}

export const activeFilters = (s: Show) =>
  (s.hideUsed !== DEFAULT_SHOW.hideUsed ? 1 : 0) +
  (s.hideSensitive ? 1 : 0) +
  (s.onlyFav ? 1 : 0) +
  (s.shape !== "all" ? 1 : 0) +
  (s.type !== "all" ? 1 : 0);

export type Days = "same" | "14" | "60" | "any" | "album";
export const DAYS: { id: Days; value: number | null }[] = [
  { id: "same", value: 21 },
  { id: "14", value: 14 },
  { id: "60", value: 60 },
  { id: "any", value: null },
  { id: "album", value: -1 },
];
export const daysLabel = (d: Days): string => i18n.t(`chooser:days.${d}`);
export const daysHint = (d: Days): string | undefined =>
  d === "same" ? i18n.t("chooser:days.sameHint") : undefined;
