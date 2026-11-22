import {
  learnedChange,
  learnedSummary,
  levelLabel,
  pct,
  SIGNAL_GROUPS,
  SIGNALS,
  signalText,
} from "./signals";

describe("signals", () => {
  it("names every signal it groups", () => {
    for (const g of SIGNAL_GROUPS)
      for (const k of g.keys) {
        expect(SIGNALS[k]).toBeDefined();
        expect(signalText(k).name).not.toContain("signals.");
      }
    expect(signalText("smile")).toEqual({ name: "Sonrisas", help: "Caras sonriendo.", penalty: undefined });
    expect(levelLabel(2)).toBe("Mucho más");
  });
  it("tells what learning changed, ignoring small moves", () => {
    expect(learnedChange(1.5, 1.6)).toBeNull();
    expect(learnedChange(1, null)).toBeNull();
    expect(pct(learnedChange(1.5, 2.25)!)).toBe("+50 %");
    expect(pct(learnedChange(-1.5, -0.75)!)).toBe("−50 %");
    const s = learnedSummary([
      { key: "smile", default: 1.5, learned: 3 },
      { key: "fav", default: 1, learned: 0.5 },
      { key: "lyric", default: 1, learned: 1.05 },
    ]);
    expect(s).toEqual({ more: ["Sonrisas"], less: ["Favoritas de Immich"] });
  });
});
