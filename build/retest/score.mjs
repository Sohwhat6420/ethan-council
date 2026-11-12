#!/usr/bin/env node
// Score the retest: agreement with the owner's original choices, by stratum, confidence and think time; Cohen's kappa.
// Writes RESULTS.md next to the responses (local, git-ignored) and prints aggregate numbers only.
//
//   node score.mjs [--data-dir <dir>] [--items <items.json>] [--responses <responses.jsonl>] [--out <RESULTS.md>]

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { renderResults, score } from "./lib.mjs";
import { DEFAULT_DATA_DIR, readJsonl } from "./select.mjs";

function args(argv) {
  const o = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) o[a.slice(2)] = argv[++i];
  }
  return o;
}

export function runScore({ dataDir = DEFAULT_DATA_DIR, itemsPath, responsesPath, outPath, title } = {}) {
  const itemsFile = itemsPath || resolve(dataDir, "items.json");
  const responsesFile = responsesPath || resolve(dataDir, "responses.jsonl");
  const out = outPath || resolve(dataDir, "RESULTS.md");
  const { items, meta } = JSON.parse(readFileSync(itemsFile, "utf8"));
  const responses = existsSync(responsesFile) ? readJsonl(responsesFile) : [];
  const s = score(items, responses, meta);
  const md = renderResults(s, { title: title || `Self-consistency retest (${meta.seed}): results` });
  writeFileSync(out, md, "utf8");
  return { summary: s, out };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const a = args(process.argv.slice(2));
  const { summary, out } = runScore({
    dataDir: resolve(a["data-dir"] || process.env.RETEST_DATA_DIR || DEFAULT_DATA_DIR),
    itemsPath: a.items ? resolve(a.items) : undefined,
    responsesPath: a.responses ? resolve(a.responses) : undefined,
    outPath: a.out ? resolve(a.out) : undefined,
  });
  console.log(JSON.stringify(summary, null, 1));
  console.log(`written ${out}`);
}
