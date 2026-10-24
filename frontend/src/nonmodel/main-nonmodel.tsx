// Concept B NON-MODEL entrypoint — a SEPARATE build output
// (static/react/finco-nonmodel.*), served only by the gated non-model host
// page.  The MODEL bundle never imports this module or the fixtures under it.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { FincoNonModelExperience } from "./FincoNonModelExperience";
import "./nonmodel.css";

const host = document.getElementById("finco-react-root");
if (host && host.dataset.surface === "non-model") {
  createRoot(host).render(
    <StrictMode>
      <FincoNonModelExperience />
    </StrictMode>,
  );
}
