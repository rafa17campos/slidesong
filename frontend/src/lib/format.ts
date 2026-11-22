import { locale } from "@/i18n";

/** «12 MB», «1.4 GB» (in the interface language) */
export const fmtSize = (b?: number | null) =>
  b == null
    ? ""
    : b > 1e9
      ? `${(b / 1e9).toLocaleString(locale(), { maximumFractionDigits: 1 })} GB`
      : `${Math.max(1, Math.round(b / 1e6))} MB`;
