// Synthetic rows in the shape of build/data/test.jsonl. Nothing here comes from real transcripts.
// Used by the tests and the headless smoke test. Deterministic.

import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const TOPICS = [
  ["Which colour should the status light use?", "Design", ["Amber", "Teal", "Grey"]],
  ["Run the long test now or overnight?", "Scheduling", ["Now", "Overnight", "Split it"]],
  ["Keep the old script or replace it?", "Clean-up", ["Keep", "Replace"]],
  ["How many retries before giving up?", "Robustness", ["One", "Three", "Ten", "Never"]],
  ["Which font pairing for the report?", "Typography", ["Serif heading, sans body", "All sans", "All serif"]],
  ["Should the lane write to the shared folder?", "Routing", ["Yes", "No, scratch only"]],
  ["Where does the summary go?", "Records", ["HANDOVER.md", "README.md", "A new file"]],
  ["Dark theme by default?", "Design", ["Follow the system", "Always dark", "Always light"]],
];

export function makeRows(n = 60, seed = 7) {
  let s = seed;
  const rand = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
  const rows = [];
  for (let i = 0; i < n; i++) {
    const [q, header, labels] = TOPICS[i % TOPICS.length];
    const nOpt = labels.length;
    const recIdx = rand() < 0.78 ? 0 : null;              // like the real data, the recommendation is usually first
    const answer = recIdx === null ? Math.floor(rand() * nOpt) : rand() < 0.8 ? 0 : 1 + Math.floor(rand() * (nOpt - 1));
    const options = labels.map((l, j) => ({
      label: j === recIdx ? `${l} (Recommended)` : l,
      description: j === recIdx && i % 3 === 0 ? `Recommended: the safe default for case ${i}.` : `Option ${j + 1} for case ${i}.`,
    }));
    const day = 3 + (i % 7);
    rows.push({
      id: `fx${String(i).padStart(4, "0")}aaaaaaaaaa`.slice(0, 16),
      ts: `2026-11-${String(day).padStart(2, "0")}T${String(8 + (i % 12)).padStart(2, "0")}:${String((i * 7) % 60).padStart(2, "0")}:00.000Z`,
      project: i % 5 === 0 ? "C--Users-someone-coursework" : "C--Users-someone-notes",
      session: `sess${i % 4}`,
      header,
      question: `${q} (case ${i})`,
      options,
      multi: false,
      rec_idx: recIdx,
      answer_kind: "option",
      answer_idx: answer,
      answer_set: [],
      answer_text: "",
      scrub_counts: {},
    });
  }
  // One row that still carries a cue after stripping, to test exclusion.
  rows.push({ ...rows[0], id: "fxcue000000000000", question: "I recommend we ship. Agree? (case cue)", rec_idx: null });
  return rows;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const out = resolve(dirname(fileURLToPath(import.meta.url)), "fixture-rows.jsonl");
  writeFileSync(out, makeRows().map((r) => JSON.stringify(r)).join("\n") + "\n", "utf8");
  console.log(`wrote ${out}`);
}
