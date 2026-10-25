import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// FINCO Model React frontend (UX-01 PoC).
//
// Production assets are served by FastAPI from the EXISTING same-origin
// `/static` mount (static/react/**).  Output file names are stable (no content
// hash) so the Jinja host page (app/templates/v2/react_poc.html) can reference
// them and the Python test-suite can assert the served bundle; cache busting is
// done with the asset-version query parameter the host page appends.
export default defineConfig({
  plugins: [react()],
  base: "/static/react/",
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        entryFileNames: "finco-react.js",
        chunkFileNames: "finco-react.js",
        assetFileNames: "finco-react.[ext]",
      },
    },
  },
});
