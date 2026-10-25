// Loads frontend/src/app/units.ts without relying on the Node version's TypeScript
// support (the CI runtime image ships Node 18, which cannot import .ts).  The file is
// transpiled with the repository's own `typescript` package (the toolchain the typecheck
// and build already use) into a temporary ES module and imported from there.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, "..", "..");
const require = createRequire(path.join(frontend, "package.json"));

export async function loadUnits() {
  const ts = require("typescript");
  const source = fs.readFileSync(path.join(frontend, "src", "app", "units.ts"), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
    fileName: "units.ts",
  });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "finco-units-"));
  const file = path.join(dir, "units.mjs");
  fs.writeFileSync(file, outputText, "utf8");
  try {
    return await import(pathToFileURL(file).href);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}
