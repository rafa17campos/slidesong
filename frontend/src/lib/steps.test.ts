import type { Project, Slot } from "@/api/types";

import { currentJob, jobTiming } from "./jobs";
import { initialStep, legacyStepUrl, stepState } from "./steps";

const slot = (asset: string | null): Slot => ({ start: 0, end: 1, lyric: "", asset });

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p",
    title: "t",
    created: "2026-11-20T10:00:00",
    song: null,
    lines: [],
    slots: [],
    assets: {},
    excluded: [],
    renders: [],
    jobs: {},
    running: null,
    cancelling: false,
    server_now: "2026-11-20T10:00:00",
    ...over,
  };
}

describe("initialStep", () => {
  it("goes to the running job's step", () => {
    expect(initialStep(project({ running: "render", slots: [slot("a")] }), "photos")).toBe("video");
  });
  it("starts with the song while nothing is analyzed", () => {
    expect(initialStep(project(), "storyboard")).toBe("song");
  });
  it("goes to photos when the song is analyzed but nothing suggested", () => {
    expect(initialStep(project({ slots: [slot(null)] }), "video")).toBe("photos");
  });
  it("returns to the last step visited once the project is set up", () => {
    expect(initialStep(project({ slots: [slot("a")] }), "video")).toBe("video");
  });
  it("defaults to the storyboard", () => {
    expect(initialStep(project({ slots: [slot("a")] }), null)).toBe("storyboard");
    expect(initialStep(project({ slots: [slot("a")] }), "nonsense")).toBe("storyboard");
  });
});

describe("stepState", () => {
  it("marks the working step", () => {
    expect(stepState(project({ running: "suggest" }), "photos")).toBe("working");
  });
  it("the storyboard is done only when every shot has a photo", () => {
    expect(stepState(project({ slots: [slot("a"), slot(null)] }), "storyboard")).toBe("todo");
    expect(stepState(project({ slots: [slot("a"), slot("b")] }), "storyboard")).toBe("done");
  });
});

describe("jobs", () => {
  it("estimates the time left from the progress so far", () => {
    const t = jobTiming("2026-11-20T10:00:00", 0.25, "2026-11-20T10:01:00");
    expect(t).toEqual({ elapsed: 60, left: 180 });
  });
  it("gives no estimate right at the start", () => {
    expect(jobTiming("2026-11-20T10:00:00", 0.01, "2026-11-20T10:00:10")?.left).toBeNull();
  });
  it("a job just started is shown as running, not with its previous state", () => {
    const old = {
      state: "cancelled" as const,
      progress: 0.4,
      error: null,
      where: null,
      finished: "2026-11-20T09:59:59",
    };
    expect(currentJob(project({ running: "render", jobs: { render: old } }))?.job).toMatchObject({
      state: "running",
      progress: 0,
    });
  });
  it("shows the most recent failure that was not dismissed", () => {
    const err = (started: string) => ({
      state: "error" as const,
      progress: 0,
      error: "x",
      where: null,
      started,
    });
    const p = project({ jobs: { suggest: err("2026-11-20T09:00:00"), render: err("2026-11-20T09:30:00") } });
    expect(currentJob(p)?.kind).toBe("render");
    expect(currentJob(p, ["p:render:2026-11-20T09:30:00"])?.kind).toBe("suggest");
  });
  it("shows a recent cancel but not an old one", () => {
    const job = { state: "cancelled" as const, progress: 0, error: null, where: null };
    const recent = project({ jobs: { render: { ...job, finished: "2026-11-20T09:59:50" } } });
    const old = project({ jobs: { render: { ...job, finished: "2026-11-20T09:50:00" } } });
    expect(currentJob(recent)?.kind).toBe("render");
    expect(currentJob(old)).toBeNull();
  });
});

describe("legacyStepUrl", () => {
  it("sends the old Spanish step addresses to the new ones", () => {
    expect(legacyStepUrl("p", "montaje", "?plano=3&intercambio=4")).toBe("/p/p/storyboard?shot=3&swap=4");
    expect(legacyStepUrl("p", "cancion", "")).toBe("/p/p/song");
    expect(legacyStepUrl("p", "nonsense", "")).toBeNull();
  });
});
