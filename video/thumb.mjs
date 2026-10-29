// Render thumb.html to the two YouTube thumbnail sizes.
// Usage: node thumb.mjs <out_dir>
import { chromium } from "playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";
const here = path.dirname(fileURLToPath(import.meta.url));
const out = process.argv[2];
const browser = await chromium.launch();
for (const [w, h] of [[1920, 1080], [1280, 720]]) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: w / 1920 });
  await page.goto(`file://${here}/thumb.html`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: path.join(out, `asli_thumbnail_${w}x${h}.png`) });
  await page.close();
}
await browser.close();
console.log("saved");
