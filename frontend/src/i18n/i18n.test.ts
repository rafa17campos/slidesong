import i18n from "@/i18n";

import { en, LANGUAGE_CODES, resources } from "./resources";

/** "a.b.c" paths of every text, plural suffixes folded ("n_one", "n_other" -> "n"). */
function keys(o: object, prefix = ""): string[] {
  return Object.entries(o).flatMap(([k, v]) =>
    v && typeof v === "object"
      ? keys(v as object, `${prefix}${k}.`)
      : [`${prefix}${k.replace(/_(zero|one|two|few|many|other)$/, "")}`],
  );
}

describe("translations", () => {
  it("every language has the same texts as English", () => {
    for (const l of LANGUAGE_CODES.filter((x) => x !== "en"))
      for (const ns of Object.keys(en) as (keyof typeof en)[]) {
        const a = new Set(keys(en[ns]));
        const b = new Set(keys(resources[l]![ns] ?? {}));
        expect([...a].filter((k) => !b.has(k)).map((k) => `${l} is missing ${ns}:${k}`)).toEqual([]);
        expect([...b].filter((k) => !a.has(k)).map((k) => `${l} has extra ${ns}:${k}`)).toEqual([]);
      }
  });
  it("no text is empty", () => {
    const empty = (o: object, p: string): string[] =>
      Object.entries(o).flatMap(([k, v]) =>
        v && typeof v === "object" ? empty(v as object, `${p}${k}.`) : v === "" ? [`${p}${k}`] : [],
      );
    for (const l of LANGUAGE_CODES)
      for (const [ns, texts] of Object.entries(resources[l]!))
        expect(empty(texts, `${l} ${ns}:`)).toEqual([]);
  });
});

describe("languages", () => {
  it("English is the source and Spanish follows it", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("common:steps.storyboard")).toBe("Storyboard");
    expect(i18n.t("terms:warnings.repeat.same", { n: 3 })).toBe("The same photo as shot 3");
    await i18n.changeLanguage("es");
    expect(i18n.t("common:steps.storyboard")).toBe("Montaje");
  });
});
