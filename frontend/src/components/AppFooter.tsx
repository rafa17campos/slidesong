import { useTranslation } from "react-i18next";

import { useConfig } from "@/api/queries";

/** Free software notice and the link to the source of what is running (AGPL-3.0). */
export function AppFooter() {
  const { t } = useTranslation();
  const { data: config } = useConfig();
  return (
    <footer className="app-footer text-caption muted">
      {t("footer.free")}{" "}
      {config?.source_url && (
        <a href={config.source_url} target="_blank" rel="noreferrer">
          {t("footer.source")}
        </a>
      )}
    </footer>
  );
}
