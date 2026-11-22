import type { ProjectSummary } from "@/api/types";
import { grouped, projectState } from "@/routes/Home";

import { changedSinceSuggest, dateShortcuts, dateTyped } from "./PhotosStep";
import { estimates } from "./VideoStep";

const base: ProjectSummary = {
  id: "p",
  title: "t",
  updated: null,
  cover: null,
  slots: 0,
  renders: 0,
  song: false,
  photos: 0,
  finals: 0,
  running: null,
  progress: null,
  frozen: false,
  parent: null,
};

describe("projectState", () => {
  it("says the next thing to do", () => {
    expect(projectState(base).next).toBe("Subir el MP3");
    expect(projectState({ ...base, song: true }).next).toBe("Analizar la canción");
    expect(projectState({ ...base, song: true, slots: 30 }).to).toBe("/p/p/photos");
    expect(projectState({ ...base, song: true, slots: 30, photos: 30 }).badge).toBe("Paso 3 · Montaje");
    expect(projectState({ ...base, song: true, slots: 30, photos: 30, finals: 1 }).tone).toBe("ok");
    expect(projectState({ ...base, running: "render", progress: 0.42 }).badge).toBe(
      "Montando el vídeo · 42 %",
    );
  });
});

describe("dateShortcuts", () => {
  it("uses last summer before June", () => {
    expect(dateShortcuts(new Date(2026, 2, 10))[0]).toEqual(["Este verano", "2025-06-01", "2025-09-30"]);
    expect(dateShortcuts(new Date(2026, 10, 20))[0]).toEqual(["Este verano", "2026-06-01", "2026-09-30"]);
    expect(dateShortcuts(new Date(2026, 10, 20))[1]).toEqual(["Últimos 6 meses", "2026-05-20", "2026-11-20"]);
    expect(dateShortcuts(new Date(2026, 10, 20))[2]).toEqual(["Todo 2026", "2026-01-01", "2026-12-31"]);
  });
});

describe("estimates", () => {
  it("grows with the quality", () => {
    const e = estimates(192);
    expect(e.final.time).toBeLessThan(e.final2k.time);
    expect(e.final2k.size).toBeLessThan(e.final4k.size);
    expect(Math.round(e.final.size / 1e6)).toBe(250); // measured: 246 MB for 3:12 at 1080p60
  });
});

describe("grouped", () => {
  it("puts versions right after the project they come from", () => {
    const list = [
      { ...base, id: "v2", parent: "a" },
      { ...base, id: "b" },
      { ...base, id: "a" },
      { ...base, id: "v3", parent: "v2" },
      { ...base, id: "orphan", parent: "gone" },
    ];
    expect(grouped(list).map((x) => [x.p.id, x.of?.id ?? null])).toEqual([
      ["b", null],
      ["a", null],
      ["v2", "a"],
      ["v3", "v2"],
      ["orphan", null],
    ]);
  });
});

describe("dateTyped", () => {
  const el = (value: string, badInput = false) => ({ value, validity: { badInput } });
  it("waits until a whole date has been typed", () => {
    expect(dateTyped(el("", true))).toBeUndefined(); // partial: day typed, year not yet
    expect(dateTyped(el("0002-06-01"))).toBeUndefined(); // the year on its way
    expect(dateTyped(el("2025-06-01"))).toBe("2025-06-01");
    expect(dateTyped(el(""))).toBeNull(); // cleared
  });
});

describe("changedSinceSuggest", () => {
  it("names the settings that changed since the last suggestion", () => {
    const p = {
      slots: [{ asset: "a" }],
      people: ["Nico", "Lía"],
      date_from: "2026-06-01",
      videos: "many",
      theme: "",
      suggested_with: { people: ["Nico"], date_from: "2026-06-01", videos: "some", theme: null },
    } as unknown as Parameters<typeof changedSinceSuggest>[0];
    expect(changedSinceSuggest(p)).toEqual(["Quién sale", "Vídeos"]);
    expect(changedSinceSuggest({ ...p, suggested_with: undefined })).toEqual([]);
  });
  it("an empty tuning is the same as none, a level is a change", () => {
    const p = {
      slots: [{ asset: "a" }],
      tuning: {},
      suggested_with: { tuning: null },
    } as unknown as Parameters<typeof changedSinceSuggest>[0];
    expect(changedSinceSuggest(p)).toEqual([]);
    expect(changedSinceSuggest({ ...p, tuning: { smile: 1 }, avoid: "playa" })).toEqual([
      "Evitar",
      "Ajustes de este proyecto",
    ]);
  });
});
