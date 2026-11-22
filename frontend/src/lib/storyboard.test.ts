import type { Plan, Project, Slot } from "@/api/types";

import { groupBySection, matches, moveState, warningsFor } from "./storyboard";

const slot = (i: number, extra: Partial<Slot> = {}): Slot => ({
  start: i * 4,
  end: i * 4 + 4,
  lyric: "",
  asset: `a${i}`,
  ...extra,
});

const project = (slots: Slot[], over: Partial<Project> = {}): Project => ({
  id: "p",
  title: "t",
  created: "",
  song: null,
  lines: [],
  slots,
  assets: {},
  excluded: [],
  renders: [],
  jobs: {},
  running: null,
  cancelling: false,
  server_now: "",
  ...over,
});

const plan: Plan = {
  shots: [
    { slots: [0], kind: "in", start: 0, end: 4, zones: [80, 115], move: 1.3 },
    { slots: [1, 2], kind: "diptych", start: 4, end: 12 },
    { slots: [3], kind: "video", start: 12, end: 16 },
  ],
  boundaries: [],
  sections: [
    { slot: 0, kind: "verse", name: "Estrofa", label: "Verse 1" },
    { slot: 2, kind: "chorus", name: "Estribillo", label: "Chorus", mood: "high" },
  ],
  repeats: [{ a: 0, b: 3, kind: "similar", sim: 0.87 }],
};

describe("groupBySection", () => {
  it("splits the shots by section with their times", () => {
    const g = groupBySection(project([0, 1, 2, 3].map((i) => slot(i))), plan);
    expect(g.map((x) => [x.section?.name, x.slots, x.from, x.to])).toEqual([
      ["Estrofa", [0, 1], 0, 8],
      ["Estribillo", [2, 3], 8, 16],
    ]);
  });
  it("is one group without a plan", () => {
    expect(groupBySection(project([slot(0), slot(1)]), undefined)).toHaveLength(1);
  });
});

describe("warnings", () => {
  const p = project([
    slot(0, { why: { a0: ["⚠️ en bañador", "🎵 letra"] } }),
    slot(1),
    slot(2, { asset: null }),
    slot(3),
  ]);
  it("lists sensitive, repeat and pixelation warnings with what fixes them", () => {
    expect(warningsFor(p, plan, 0)).toEqual([
      { kind: "sensitive", text: "Foto sensible: en bañador" },
      { kind: "repeat", text: "Muy parecida al plano 4 (87 %)", other: 3, sim: 0.87 },
      { kind: "pixelate", text: "El movimiento pixelará" },
    ]);
    expect(warningsFor(p, plan, 3)[0]).toMatchObject({ kind: "repeat", other: 0 });
    expect(warningsFor(p, plan, 1)).toEqual([]);
    expect(warningsFor(p, plan, 2)).toEqual([{ kind: "empty", text: "Este plano no tiene foto" }]);
  });
  it("a pinned photo's warnings count as reviewed", () => {
    const pinned = project([
      slot(0, { locked: true, why: { a0: ["⚠️ en bañador"] } }),
      slot(1),
      slot(2),
      slot(3),
    ]);
    const w = warningsFor(pinned, plan, 0);
    expect(w.filter((x) => x.kind !== "pixelate").every((x) => x.reviewed)).toBe(true);
    expect(matches(pinned, plan, 0, "warnings")).toBe(true); // the pixelation is still open
    expect(warningsFor(pinned, plan, 3)[0]).toMatchObject({ kind: "repeat", other: 0 }); // the other one still counts
    expect(warningsFor(pinned, plan, 3)[0]?.reviewed).toBeUndefined();
  });
  it("filters", () => {
    expect([0, 1, 2, 3].filter((i) => matches(p, plan, i, "warnings"))).toEqual([0, 2, 3]);
  });
});

describe("moveState", () => {
  it("reads the automatic value capped by resolution", () => {
    expect(
      moveState({
        slots: [0],
        kind: "in",
        start: 0,
        end: 1,
        res_limited: true,
        auto_pct: 75,
        zones: [80, 115],
      }),
    ).toMatchObject({ auto: true, value: 75, zone: "green", autoLimited: true });
  });
  it("puts a manual value in its zone", () => {
    const sh = { slots: [0], kind: "in", start: 0, end: 1, zones: [80, 115] as [number, number] };
    expect(moveState({ ...sh, move: 0.9 }).zone).toBe("yellow");
    expect(moveState({ ...sh, move: 1.2 }).zone).toBe("red");
    expect(moveState({ ...sh, zones: [null, null], move: 1.5 }).zone).toBe("green");
  });
});

import { sectionName } from "./names";

describe("sectionName", () => {
  it("numbers sections when Suno does", () => {
    expect(sectionName({ name: "Estrofa", label: "Verse 2 – Acoustic guitars, 3 chords" })).toBe("Estrofa 2");
    expect(sectionName({ name: "Estribillo", label: "Final Chorus – Rich" })).toBe("Estribillo");
    expect(sectionName(null)).toBe("Canción");
  });
});
