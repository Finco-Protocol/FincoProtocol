import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Concept B NON-MODEL preview build — a SEPARATE entrypoint and output so the
// MODEL production bundle (finco-react.*) never includes the non-model
// experience or its synthetic fixtures.  Served by the gated
// GET /v2/non-model host page (FINCO_NONMODEL_PREVIEW, default OFF).
export default defineConfig({
  plugins: [react()],
  base: "/static/react/",
  build: {
    outDir: "dist-nonmodel",
    sourcemap: false,
    rollupOptions: {
      // EXPLICIT non-model entrypoint — without this, Vite falls back to the
      // model index.html and the output would silently be the MODEL app.
      input: { "finco-nonmodel": "src/nonmodel/main-nonmodel.tsx" },
      output: {
        entryFileNames: "finco-nonmodel.js",
        chunkFileNames: "finco-nonmodel.js",
        assetFileNames: "finco-nonmodel.[ext]",
      },
    },
  },
});
