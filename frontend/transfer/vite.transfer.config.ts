import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// DEV-ONLY design-transfer preview for the harvested Replit source
// (frontend/src/finco/**).  This build is NOT served by FastAPI, NOT referenced
// by any production surface, and NOT wired into CI.  Its purpose is to keep the
// harvested design source compiling and reviewable while the domain-by-domain
// integration (UX-01B follow-ups) replaces the PoC views.
//
// Adaptations vs. the supplied sandbox config:
//   - the Tailwind v4 gallery entry (src/index.css) is NOT part of the FINCO
//     fm-* design system; the harness imports src/finco/_group.css instead.
//   - the sandbox "@" alias and preview plumbing are dropped (no usage in the
//     harvested subtree; imports are relative).
const frontendRoot = path.resolve(import.meta.dirname, "..");

export default defineConfig({
  root: frontendRoot,
  base: process.env.BASE_PATH || "/",
  plugins: [react()],
  build: {
    outDir: path.resolve(frontendRoot, "dist-transfer"),
    emptyOutDir: true,
    rollupOptions: {
      input: { index: path.resolve(frontendRoot, "transfer", "index.html") },
    },
  },
  server: {
    port: Number(process.env.PORT || 5000),
  },
});
