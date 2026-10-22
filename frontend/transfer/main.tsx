import React from "react";
import { createRoot } from "react-dom/client";
import "../src/finco/_group.css";
import FincoTransferApp from "./App";

window.__FINCO_TRANSFER_APP__ = true;
window.__FINCO_TRANSFER_BASE__ = "/";

const root = document.getElementById("root");
if (!root) throw new Error("FINCO transfer entry is missing its #root element.");
createRoot(root).render(<FincoTransferApp />);
