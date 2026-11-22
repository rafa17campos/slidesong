import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@/i18n";
import { App } from "@/app/App";
import "@/styles/index.css";

// links to the classic page (/#/p/<id>) open the same project here
const legacy = window.location.hash.match(/^#\/p\/([a-z0-9-]+)/);
if (legacy) window.history.replaceState(null, "", `${import.meta.env.BASE_URL}p/${legacy[1]}`);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
