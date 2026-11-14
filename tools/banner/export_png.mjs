// Renders the social preview SVG to PNG with Playwright's bundled headless Chromium (never the user's own browser).
//   node tools/banner/export_png.mjs
// Set PLAYWRIGHT_DIR to a folder holding the playwright package if it is not installed where Node can find it.
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const dir = process.env.PLAYWRIGHT_DIR;
const { chromium } = dir
  ? await import(pathToFileURL(path.join(dir, "index.mjs")).href)
  : createRequire(import.meta.url)("playwright");
const assets = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "assets");
const jobs = [["banner-1280x640", 1280, 640]];

const browser = await chromium.launch({ headless: true });
try {
  for (const [name, w, h] of jobs) {
    const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1, reducedMotion: "reduce" });
    await page.goto(pathToFileURL(path.join(assets, name + ".svg")).href);
    await page.screenshot({ path: path.join(assets, name + ".png"), clip: { x: 0, y: 0, width: w, height: h } });
    await page.close();
    console.log(`assets/${name}.png ${w}x${h}`);
  }
} finally {
  await browser.close();
}
