import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const staticSrc = resolve(root, "..");
const outputDir = resolve(staticSrc, "../static/js/dist");

mkdirSync(outputDir, { recursive: true });
copyFileSync(
  resolve(staticSrc, "node_modules/lucide/dist/umd/lucide.min.js"),
  resolve(outputDir, "lucide.min.js"),
);
