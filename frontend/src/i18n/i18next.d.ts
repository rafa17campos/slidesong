import "i18next";

import type { Resources } from "./resources";

// t("photos:theme.label") is checked against the English texts: a missing or misspelled key is a type error.
declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "common";
    resources: Resources;
  }
}
