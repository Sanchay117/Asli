// Record real takes of the hosted Asli app at 1920x1080 with a visible cursor.
// Usage: node record.mjs <take> <out_dir>
//   takes: amazon | flipkart | watch | hood
// Writes <out_dir>/<take>.webm and <out_dir>/<take>.marks.json (seconds from video start).
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.ASLI_URL || "https://asli-1ixl.onrender.com";
const [take, outDir] = process.argv.slice(2);
const SHOT = "/private/tmp/claude-501/-Users-sanchaysingh-Desktop-Hackathons/e8b24e26-fde4-4a9c-bc76-0a48e79540c6/scratchpad/fk_3060.png";
const AMAZON = "https://www.amazon.in/GIGABYTE-WINDFORCE-pci_e_x16-Graphics-GV-N3060WF2OC-12GD/dp/B0BNP2CMXM";
const FLIPKART = "https://www.flipkart.com/gigabyte-geforce-rtx-3060-pci-e-x16-windforce-oc-12gd-gv-n3060wf2oc-12gd-gddr6-12-gb-nvidia-chipset-192-bit-1792-mhz-graphics-card/p/itmabe6891376c4e";

fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: outDir, size: { width: 1920, height: 1080 } },
  colorScheme: "dark",
});
const t0 = Date.now();
const marks = {};
const mark = (name) => { marks[name] = (Date.now() - t0) / 1000; console.log(name, marks[name].toFixed(1)); };

// Bigger UI for video, plus a cursor that follows mouse events.
await context.addInitScript(() => {
  document.addEventListener("DOMContentLoaded", () => {
    document.documentElement.style.zoom = "1.3";
    const c = document.createElement("div");
    c.id = "fake-cursor";
    c.style.cssText = "position:fixed;z-index:99999;width:22px;height:22px;border-radius:50%;" +
      "background:rgba(255,255,255,.9);border:2px solid #0f7a4f;box-shadow:0 2px 8px rgba(0,0,0,.4);" +
      "pointer-events:none;transform:translate(-50%,-50%);left:-50px;top:-50px;transition:transform .12s";
    document.body.appendChild(c);
    // Coordinates arrive in viewport pixels; the page is zoomed, so divide.
    window.addEventListener("mousemove", (e) => { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; }, true);
    window.addEventListener("mousedown", () => { c.style.transform = "translate(-50%,-50%) scale(.75)"; }, true);
    window.addEventListener("mouseup", () => { c.style.transform = "translate(-50%,-50%)"; }, true);
  });
});

const page = await context.newPage();

async function moveTo(locator) {
  const b = await locator.boundingBox();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 30 });
  await page.waitForTimeout(250);
}
async function click(locator) {
  await moveTo(locator);
  await page.mouse.down(); await page.waitForTimeout(90); await page.mouse.up();
}
async function smoothScroll(px, ms) {
  const steps = Math.max(1, Math.round(ms / 16));
  for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, px / steps); await page.waitForTimeout(16); }
}
async function scrollToEl(selector, ms = 1500) {
  const y = await page.evaluate((s) => {
    const el = document.querySelector(s);
    const z = parseFloat(document.documentElement.style.zoom || "1");
    return el ? el.getBoundingClientRect().top * z - 110 : 0;
  }, selector);
  await smoothScroll(y, ms);
}

await page.goto(BASE + "/#check", { waitUntil: "networkidle" });
await page.mouse.move(960, 700);
await page.waitForTimeout(1500);
mark("ready");

if (take === "amazon" || take === "flipkart") {
  const input = page.locator("#url");
  await click(input);
  await page.keyboard.type(take === "amazon" ? AMAZON : FLIPKART, { delay: 12 });
  await page.waitForTimeout(400);
  mark("typed");
  await click(page.locator("#go"));
  mark("submitted");

  if (take === "flipkart") {
    await page.locator("#shot.ask").waitFor({ timeout: 120000 });
    mark("asked_for_screenshot");
    await page.waitForTimeout(2500);
    await moveTo(page.locator("#drop"));
    await page.locator("#file").setInputFiles(SHOT);
    mark("uploaded");
  }
  await page.locator("#step-market.done, #step-market.error").waitFor({ timeout: 180000 });
  mark("evidence_done");
  await page.locator("#result:not([hidden]) .verdict").waitFor({ timeout: 180000 });
  mark("verdict");
  await page.waitForTimeout(800);
  await scrollToEl("#result", 1600);
  mark("at_verdict");
  await page.waitForTimeout(4500);
  await smoothScroll(520, 2500);
  mark("reasons");
  await page.waitForTimeout(4500);
  await scrollToEl(".table-wrap", 2000);
  mark("table");
  await page.waitForTimeout(4000);
  await smoothScroll(900, 3500);
  mark("bottom");
  await page.waitForTimeout(3000);
} else if (take === "watch" || take === "hood") {
  await click(page.locator(`.tabs button[data-tab="${take}"]`));
  mark("opened");
  await page.waitForTimeout(3500);
  await smoothScroll(take === "hood" ? 560 : 700, 4000);
  mark("scrolled");
  await page.waitForTimeout(4500);
  await smoothScroll(take === "hood" ? 600 : 900, 4500);
  mark("scrolled2");
  await page.waitForTimeout(4000);
}

const video = page.video();
await context.close();
await browser.close();
const src = await video.path();
fs.renameSync(src, path.join(outDir, `${take}.webm`));
fs.writeFileSync(path.join(outDir, `${take}.marks.json`), JSON.stringify(marks, null, 1));
console.log("saved", take);
