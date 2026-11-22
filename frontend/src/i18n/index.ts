import i18n, { type Resource, type ResourceLanguage } from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import { LANGUAGE_CODES, NAMESPACES, resources as texts } from "./resources";

export type Lang = string;

const STORE = "slidesong:lang";

/**
 * Some languages have plural forms i18next asks for that the files may not spell out (Spanish «un millón de fotos»
 * is "many"): missing forms read as "other" instead of showing a raw key.
 */
function withPlurals(lang: string, texts: Record<string, unknown>): ResourceLanguage {
  const forms = new Intl.PluralRules(lang).resolvedOptions().pluralCategories;
  const fill = (o: Record<string, unknown>) => {
    for (const [k, v] of Object.entries(o)) {
      if (v && typeof v === "object") fill(v as Record<string, unknown>);
      else if (k.endsWith("_other"))
        for (const f of forms) {
          const key = k.replace(/_other$/, `_${f}`);
          if (!(key in o)) o[key] = v;
        }
    }
  };
  const copy = structuredClone(texts);
  fill(copy);
  return copy as ResourceLanguage;
}

const resources: Resource = Object.fromEntries(LANGUAGE_CODES.map((l) => [l, withPlurals(l, texts[l]!)]));

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    ns: NAMESPACES,
    defaultNS: "common",
    fallbackLng: "en",
    supportedLngs: LANGUAGE_CODES,
    load: "languageOnly",
    interpolation: { escapeValue: false }, // React escapes already
    // the language chosen by hand, else the browser's
    detection: { order: ["localStorage", "navigator"], lookupLocalStorage: STORE, caches: [] },
    returnNull: false,
  });

const mark = (l: string) => {
  if (typeof document !== "undefined") document.documentElement.lang = l;
};
mark(i18n.resolvedLanguage ?? "en");
i18n.on("languageChanged", mark);

/** The interface language ("en", "es"…). */
export const lang = (): Lang => {
  const l = i18n.resolvedLanguage ?? "en";
  return LANGUAGE_CODES.includes(l) ? l : "en";
};

/** For dates and numbers (toLocaleDateString, Intl): each language says it in common.json. */
export const locale = () => i18n.t("common:language.locale", { lng: lang() });

/** [code, name] of every interface language, each in its own language («English», «Español»). */
export const languages = (): [Lang, string][] =>
  LANGUAGE_CODES.map((l) => [l, i18n.t("common:language.name", { lng: l })]);

/** Choose the language by hand (remembered in this browser). */
export function setLanguage(l: Lang) {
  try {
    localStorage.setItem(STORE, l);
  } catch {
    /* only for this visit */
  }
  void i18n.changeLanguage(l);
}

export default i18n;
