import React from "react";
import { createRoot } from "react-dom/client";
import "../src/finco/_group.css";
import { setFincoWorkingCopyBridge } from "../src/finco/_shared/fincoProjectBridge";
import { clearDemoSessionState } from "../src/finco/_shared/demoSession";
import { createDemoWorkingCopy, createLocalDemoProject, getDemoWorkingCopy, listDemoWorkingCopies } from "../src/finco/_shared/demoWorkingCopies";

// Demo harness only: install the local-session bridge the harvested
// components consume through the neutral seam.  Production never installs one.
setFincoWorkingCopyBridge({
  list: () => listDemoWorkingCopies(),
  read: (id) => getDemoWorkingCopy(id),
  create: (project) => createDemoWorkingCopy({ ...project, sponsor: project.templateSource || "" }),
  createBlank: (seed) => createLocalDemoProject(seed),
  clear: () => clearDemoSessionState(),
});
import FincoTransferApp from "./App";

window.__FINCO_TRANSFER_APP__ = true;
window.__FINCO_TRANSFER_BASE__ = "/";

const root = document.getElementById("root");
if (!root) throw new Error("FINCO transfer entry is missing its #root element.");
createRoot(root).render(<FincoTransferApp />);
