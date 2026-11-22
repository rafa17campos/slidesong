import type { Candidate } from "@/api/types";

import { activeFilters, chooserView, DEFAULT_SHOW } from "./chooser";

const items: Candidate[] = [
  { id: "a", fit: 1, quality: 3, days: 10, date: "2026-07-01", portrait: true },
  { id: "b", fit: 5, quality: 1, days: 2, date: "2026-08-01", landscape: true, used: true },
  {
    id: "c",
    fit: 3,
    quality: 2,
    days: 30,
    date: "2026-06-01",
    landscape: true,
    sensitive: "en bañador",
    video: true,
  },
];

describe("chooserView", () => {
  it("hides used photos by default and sorts by fit", () => {
    const v = chooserView(items, "fit", DEFAULT_SHOW);
    expect(v.visible.map((x) => x.id)).toEqual(["c", "a"]);
    expect(v.hidden).toBe(1);
  });
  it("sorts by beauty, nearness and date", () => {
    const all = { ...DEFAULT_SHOW, hideUsed: false };
    expect(chooserView(items, "quality", all).visible.map((x) => x.id)).toEqual(["a", "c", "b"]);
    expect(chooserView(items, "near", all).visible.map((x) => x.id)).toEqual(["b", "a", "c"]);
    expect(chooserView(items, "new", all).visible.map((x) => x.id)).toEqual(["b", "a", "c"]);
    expect(chooserView(items, "query", all).visible.map((x) => x.id)).toEqual(["a", "b", "c"]);
  });
  it("filters by warning, shape and type", () => {
    const s = { ...DEFAULT_SHOW, hideUsed: false, hideSensitive: true, shape: "landscape" as const };
    expect(chooserView(items, "fit", s).visible.map((x) => x.id)).toEqual(["b"]);
    expect(chooserView(items, "fit", { ...DEFAULT_SHOW, type: "video" }).visible.map((x) => x.id)).toEqual([
      "c",
    ]);
    expect(activeFilters(s)).toBe(3);
  });
});
