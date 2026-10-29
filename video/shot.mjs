// Screenshot a product page like a buyer would see it on a laptop.
// Usage: node shot.mjs <url> <out.png>
import { chromium } from "playwright";
const [url, out] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1366, height: 900 }, locale: "en-IN" });
await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(4000);
await page.screenshot({ path: out });
await browser.close();
console.log("saved", out);
