// Record one motion-graphics scene from scenes.html.
// Usage: node record_scene.mjs <scene> <seconds> <out_dir>
// Writes <out_dir>/<scene>.webm and <scene>.start (seconds of lead-in to trim).
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const [scene, seconds, outDir] = process.argv.slice(2);
const here = path.dirname(fileURLToPath(import.meta.url));
fs.mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: outDir, size: { width: 1920, height: 1080 } },
});
const t0 = Date.now();
const page = await context.newPage();
await page.goto(`file://${here}/scenes.html?s=${scene}`);
await page.waitForFunction(() => document.title === "started", null, { timeout: 30000 });
const start = (Date.now() - t0) / 1000;
await page.waitForTimeout(Number(seconds) * 1000 + 300);
const video = page.video();
await context.close();
await browser.close();
fs.renameSync(await video.path(), path.join(outDir, `${scene}.webm`));
fs.writeFileSync(path.join(outDir, `${scene}.start`), String(start));
console.log(scene, "start", start.toFixed(2));
