#!/usr/bin/env node
// Headless smoke test on FIXTURE data (never the owner's rows): starts a server on an ephemeral port over a scratch data
// dir, renders the intro and the first question with Playwright's bundled Chromium (never an installed browser or
// profile), in light and dark, at phone and laptop widths. Screenshots go to --out (default: the OS temp dir).
// Prints pass/fail lines only. Works on Windows, Linux and macOS.
//
//   node smoke.mjs [--out <dir>] [--chrome <path to chrome or chrome-headless-shell>]
//   env: RETEST_CHROME (same as --chrome), PLAYWRIGHT_BROWSERS_PATH (where Playwright keeps its browsers)

import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, mkdirSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { makeRows } from "./fixtures/make-fixture.mjs";
import { createApp, listen } from "./server.mjs";

function args(argv) {
  const o = {};
  for (let i = 0; i < argv.length; i++) if (argv[i].startsWith("--")) o[argv[i].slice(2)] = argv[++i];
  return o;
}

// Where Playwright keeps its browsers on each platform, most specific first.
function playwrightRoots() {
  const roots = [];
  if (process.env.PLAYWRIGHT_BROWSERS_PATH) roots.push(process.env.PLAYWRIGHT_BROWSERS_PATH);
  if (process.env.LOCALAPPDATA) roots.push(join(process.env.LOCALAPPDATA, "ms-playwright"));
  roots.push(join(homedir(), ".cache", "ms-playwright"), join(homedir(), "Library", "Caches", "ms-playwright"));
  return roots.filter((r) => existsSync(r));
}

// Playwright's chrome-headless-shell (old headless) first: it honours --virtual-time-budget and captured in under 2 s,
// while chrome --headless=new hung on --virtual-time-budget and captured too early with --timeout (11 Nov).
// Layout: chromium_headless_shell-<rev>/chrome-headless-shell-<platform>/chrome-headless-shell[.exe] and
// chromium-<rev>/chrome-<platform>/chrome[.exe] (or Chromium.app on macOS).
function findChrome(explicit) {
  const given = explicit || process.env.RETEST_CHROME;
  if (given) return { exe: given, shell: /headless.shell/i.test(given) };
  const byRev = (root, re) => readdirSync(root).filter((d) => re.test(d)).sort((a, b) => Number(b.split("-").pop()) - Number(a.split("-").pop()));
  const inside = (dir, names) => {
    for (const sub of existsSync(dir) ? readdirSync(dir) : []) {
      for (const n of names) {
        const exe = join(dir, sub, n);
        if (existsSync(exe)) return exe;
      }
    }
    return null;
  };
  for (const root of playwrightRoots()) {
    for (const d of byRev(root, /^chromium_headless_shell-\d+$/)) {
      const exe = inside(join(root, d), ["chrome-headless-shell.exe", "chrome-headless-shell"]);
      if (exe) return { exe, shell: true };
    }
    for (const d of byRev(root, /^chromium-\d+$/)) {
      const exe = inside(join(root, d), ["chrome.exe", "chrome", join("Chromium.app", "Contents", "MacOS", "Chromium")]);
      if (exe) return { exe, shell: false };
    }
  }
  return null;
}

// Async on purpose: the fixture server runs in this same process, so a blocking spawnSync would starve it and
// Chromium would wait forever for /api/items.
function chrome({ exe, shell }, profile, url, { width, height, screenshot, dumpDom }) {
  const a = [
    shell ? "--headless" : "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-sync", "--disable-background-networking", "--disable-component-update", "--mute-audio",
    // The page is served from 127.0.0.1 by this process: never route it, or Chromium's own background calls, through a
    // system or environment proxy (on Linux a proxy in the environment made every launch hang until the kill timer).
    "--no-proxy-server",
    // A fresh profile per run: a reused one makes the next instance wait on the exiting one.
    `--user-data-dir=${mkdtempSync(profile + "-")}`, `--window-size=${width},${height}`,
    shell ? "--virtual-time-budget=5000" : "--timeout=6000", "--run-all-compositor-stages-before-draw",
  ];
  // Chromium refuses to start as root on Linux without this (containers, CI). Never needed on Windows or macOS.
  if (process.platform === "linux" && process.getuid?.() === 0) a.push("--no-sandbox");
  if (screenshot) a.push(`--screenshot=${screenshot}`);
  if (dumpDom) a.push("--dump-dom");
  a.push(url);
  return new Promise((done) => {
    const child = spawn(exe, a, { windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    const timer = setTimeout(() => child.kill(), Number(process.env.SMOKE_LAUNCH_MS) || 45000);
    child.on("close", (code) => { clearTimeout(timer); done({ code, out, err }); });
    child.on("error", (e) => { clearTimeout(timer); done({ code: null, out, err: String(e) }); });
  });
}

const a = args(process.argv.slice(2));
const exe = findChrome(a.chrome);
const results = [];
const ok = (name, cond, extra = "") => { results.push([cond, name, extra]); };

if (!exe) {
  console.log("FAIL no Playwright Chromium found (looked in PLAYWRIGHT_BROWSERS_PATH and the default ms-playwright folders); pass --chrome <path>");
  process.exit(2);
}

const scratch = mkdtempSync(join(tmpdir(), "retest-smoke-"));
const outDir = resolve(a.out || join(scratch, "shots"));
mkdirSync(outDir, { recursive: true });
const src = join(scratch, "rows.jsonl");
writeFileSync(src, makeRows().map((r) => JSON.stringify(r)).join("\n") + "\n");
const app = createApp({ dataDir: join(scratch, "data"), source: src });
const port = await listen(app, 0);
const base = `http://127.0.0.1:${port}/`;
const profile = join(scratch, "profile");

try {
  const shots = [
    ["intro-light-laptop.png", `${base}?theme=light`, 1280, 900],
    ["question-light-laptop.png", `${base}?go=1&theme=light`, 1280, 900],
    ["question-dark-laptop.png", `${base}?go=1&theme=dark`, 1280, 900],
    ["question-light-phone.png", `${base}?go=1&theme=light`, 390, 844],
    ["question-dark-phone.png", `${base}?go=1&theme=dark`, 390, 844],
  ];
  for (const [name, url, w, h] of shots) {
    const file = join(outDir, name);
    const r = await chrome(exe, profile, url, { width: w, height: h, screenshot: file });
    const size = existsSync(file) ? statSync(file).size : 0;
    ok(`screenshot ${name}`, r.code === 0 && size > 2000, `exit=${r.code} bytes=${size}`);
  }
  const dom = await chrome(exe, profile, `${base}?go=1&theme=light`, { width: 1280, height: 900, dumpDom: true });
  ok("question screen renders an article", /<article class="q/.test(dom.out));
  ok("question screen shows options with key badges", (dom.out.match(/class="opt"/g) || []).length >= 2);
  ok("question screen shows the confidence control", /How sure are you\?/.test(dom.out));
  ok("question screen shows the context line", /Singapore time/.test(dom.out));
  ok("no recommendation cue reaches the page", !/recommend/i.test(dom.out.replace(/<script[\s\S]*?<\/script>/g, "")));
  ok("progress count reads 0 of 40", /0 of 40/.test(dom.out));
  const intro = await chrome(exe, profile, `${base}?theme=light`, { width: 1280, height: 900, dumpDom: true });
  ok("intro renders the title", /Forty of your own rulings/.test(intro.out));
} finally {
  app.server.close();
}

let failed = 0;
for (const [cond, name, extra] of results) {
  if (!cond) failed++;
  console.log(`${cond ? "ok  " : "FAIL"} ${name}${extra ? `  (${extra})` : ""}`);
}
console.log(`screenshots: ${outDir}`);
console.log(`chromium: ${exe.exe}${exe.shell ? " (headless shell)" : ""}`);
if (!a.out) console.log("(scratch kept for inspection; delete when done)");
process.exit(failed ? 1 : 0);
