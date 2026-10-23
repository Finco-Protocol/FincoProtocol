import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/finco-react.css";
import "./styles/fm-themes.css";

// Mount point: the Jinja host page (app/templates/v2/react_poc.html) provides
// #finco-react-root with data attributes.  If the root is absent (e.g. the
// bundle is served on a page that did not opt into the PoC), do nothing.
const host = document.getElementById("finco-react-root");
if (host) {
  createRoot(host).render(
    <StrictMode>
      <App host={host} />
    </StrictMode>,
  );
}
