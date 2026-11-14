// Renders the social SVGs to PNG with Playwright's bundled headless Chromium (never the user's own browser).
//   node tools/banner/export_png.mjs
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const assets = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "assets");
const jobs = [["banner-linkedin-1200x627", 1200, 627], ["banner-1280x640", 1280, 640]];

const browser = await chromium.launch({ headless: true });
for (const [name, w, h] of jobs) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1, reducedMotion: "reduce" });
  await page.goto(pathToFileURL(path.join(assets, name + ".svg")).href);
  await page.screenshot({ path: path.join(assets, name + ".png"), clip: { x: 0, y: 0, width: w, height: h } });
  await page.close();
  console.log(`assets/${name}.png ${w}x${h}`);
}
await browser.close();
