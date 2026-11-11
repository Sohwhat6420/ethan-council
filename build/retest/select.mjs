#!/usr/bin/env node
// Select the 40 retest items from the frozen test split and write items.json (local, git-ignored).
// Prints counts only; never a row's text.
//
//   node select.mjs [--source <frozen test jsonl>] [--out <items.json>] [--seed <str>] [--n 40] [--force]

import { existsSync, mkdirSync, readFileSync, writeFileSync, renameSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { selectItems } from "./lib.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
export const BUILD = resolve(HERE, "..");
export const DEFAULT_SOURCE = resolve(BUILD, "local", "test-frozen-2026-11-10.jsonl");
export const DEFAULT_DATA_DIR = resolve(BUILD, "local", "retest-2026-11-10");

export function readJsonl(path) {
  return readFileSync(path, "utf8").split(/\r?\n/).filter((l) => l.trim()).map((l) => JSON.parse(l));
}

export function writeJsonAtomic(path, obj) {
  mkdirSync(dirname(path), { recursive: true });
  const tmp = path + ".tmp";
  writeFileSync(tmp, JSON.stringify(obj, null, 1), "utf8");
  renameSync(tmp, path);
}

export function buildItems({ source = DEFAULT_SOURCE, out = resolve(DEFAULT_DATA_DIR, "items.json"), seed = "retest-2026-11-10", n = 40, force = false } = {}) {
  if (existsSync(out) && !force) {
    const existing = JSON.parse(readFileSync(out, "utf8"));
    return { ...existing, reused: true };
  }
  const rows = readJsonl(source);
  const { items, meta } = selectItems(rows, { n, seed });
  const payload = { meta: { ...meta, source: source.replace(/\\/g, "/"), generated_at: new Date().toISOString() }, items };
  writeJsonAtomic(out, payload);
  return { ...payload, reused: false };
}

function args(argv) {
  const o = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--force") o.force = true;
    else if (a.startsWith("--")) o[a.slice(2)] = argv[++i];
  }
  return o;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const a = args(process.argv.slice(2));
  const res = buildItems({
    source: a.source ? resolve(a.source) : DEFAULT_SOURCE,
    out: a.out ? resolve(a.out) : resolve(DEFAULT_DATA_DIR, "items.json"),
    seed: a.seed || "retest-2026-11-10",
    n: a.n ? Number(a.n) : 40,
    force: Boolean(a.force),
  });
  const { items, meta, reused } = res;
  console.log(JSON.stringify({ reused, n: items.length, strata: meta.strata, quotas: meta.quotas, excluded_for_cue: meta.excluded_for_cue, population: meta.population, seed: meta.seed }, null, 1));
}
