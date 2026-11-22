import "@testing-library/jest-dom/vitest";

// the tests were written against the Spanish texts
import i18n from "@/i18n";

await i18n.changeLanguage("es");
