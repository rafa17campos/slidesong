import { Languages } from "lucide-react";
import { useTranslation } from "react-i18next";

import { lang, languages, setLanguage, type Lang } from "@/i18n";

/** English / Español, in the top bar. */
export function LanguageSwitch() {
  const { t, i18n } = useTranslation();
  void i18n.resolvedLanguage; // re-render on change
  return (
    <label className="lang-switch">
      <Languages className="ico ico-sm" aria-hidden />
      <span className="sr-only">{t("language.label")}</span>
      <select
        value={lang()}
        onChange={(e) => setLanguage(e.target.value as Lang)}
        aria-label={t("language.label")}
      >
        {languages().map(([code, name]) => (
          <option key={code} value={code} lang={code}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
}
