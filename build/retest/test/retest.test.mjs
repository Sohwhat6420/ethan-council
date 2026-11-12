// node --test build/retest/test/retest.test.mjs   (synthetic fixtures only; no real rows are read)
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import http from "node:http";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { stripRecommended, rowHasCue, selectItems, prepareItem, clientView, cohenKappa, score, renderResults, validateResponse, latestResponses, humaniseProject } from "../lib.mjs";
import { makeRows } from "../fixtures/make-fixture.mjs";
import { createApp, listen } from "../server.mjs";
import { runScore } from "../score.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));

function tmp() {
  return mkdtempSync(join(tmpdir(), "retest-"));
}

function fixtureFile(dir) {
  const p = join(dir, "rows.jsonl");
  writeFileSync(p, makeRows().map((r) => JSON.stringify(r)).join("\n") + "\n");
  return p;
}

// ---------- marker stripping ----------

test("strip: parenthesised and leading markers go, text survives", () => {
  assert.equal(stripRecommended("Teal (Recommended)"), "Teal");
  assert.equal(stripRecommended("Teal [recommended]"), "Teal");
  assert.equal(stripRecommended("Teal (recommended for now)"), "Teal");
  assert.equal(stripRecommended("(Recommended) Teal"), "Teal");
  assert.equal(stripRecommended("Recommended: the safe default."), "the safe default.");
  assert.equal(stripRecommended("Strongly recommended - ship it"), "ship it");
  assert.equal(stripRecommended("Ship it - recommended"), "Ship it");
  assert.equal(stripRecommended("Keep the (old) script"), "Keep the (old) script");
  assert.equal(stripRecommended(""), "");
  assert.equal(stripRecommended(null), "");
});

test("strip: a row with a residual cue is detected and excluded from selection", () => {
  const rows = makeRows();
  const cue = rows.find((r) => r.id === "fxcue000000000000");
  assert.ok(rowHasCue(cue));
  assert.ok(!rowHasCue(rows[0]));
  const { items, meta } = selectItems(rows, { n: 40, seed: "s" });
  assert.ok(!items.some((it) => it.id === cue.id));
  assert.equal(meta.excluded_for_cue, 1);
});

test("prepared items carry no marker anywhere the client can see", () => {
  const rows = makeRows();
  const { items } = selectItems(rows, { n: 40, seed: "s" });
  for (const it of items) {
    const v = clientView(it);
    const blob = JSON.stringify(v);
    assert.ok(!/recommend/i.test(blob), "client view leaks a recommendation cue");
    assert.ok(!("answer_idx" in v) && !("rec_idx" in v) && !("perm" in v) && !("stratum" in v));
    assert.equal(v.options.length, it.options.length);
    assert.ok(v.context.includes("Singapore time"));
  }
});

// ---------- selection ----------

test("selection is deterministic for a seed and changes with the seed", () => {
  const rows = makeRows();
  const a = selectItems(rows, { n: 40, seed: "retest-2026-11-10" });
  const b = selectItems(rows, { n: 40, seed: "retest-2026-11-10" });
  const c = selectItems(rows, { n: 40, seed: "another" });
  assert.deepEqual(a.items.map((i) => i.id), b.items.map((i) => i.id));
  assert.deepEqual(a.items.map((i) => i.perm), b.items.map((i) => i.perm));
  assert.notDeepEqual(a.items.map((i) => i.id), c.items.map((i) => i.id));
  assert.equal(a.items.length, 40);
  assert.equal(new Set(a.items.map((i) => i.id)).size, 40);
});

test("selection is stratified and includes overrides; order interleaves strata", () => {
  const rows = makeRows(120, 3);
  const { items, meta } = selectItems(rows, { n: 40, seed: "s" });
  assert.ok(meta.strata.override >= 1, "no override rows selected");
  assert.equal(meta.strata.override + meta.strata.follow + meta.strata.norec, 40);
  const first10 = items.slice(0, 10).map((i) => i.stratum);
  assert.ok(new Set(first10).size > 1, "strata are grouped, not interleaved");
  assert.ok(items.every((it, i) => it.position === i));
});

test("a short stratum is topped up from the others", () => {
  const rows = makeRows(60, 5).filter((r) => !(r.rec_idx !== null && r.answer_idx !== r.rec_idx)).slice(0, 50); // no overrides at all
  const { items, meta } = selectItems(rows, { n: 40, seed: "s" });
  assert.equal(items.length, 40);
  assert.equal(meta.strata.override || 0, 0);
});

test("shuffle permutation is recorded and maps back to the original answer", () => {
  const row = makeRows()[3];
  const it = prepareItem(row, "s", 0);
  assert.equal(it.perm.length, row.options.length);
  assert.deepEqual([...it.perm].sort(), row.options.map((_, i) => i));
  const shownIdxOfAnswer = it.perm.indexOf(row.answer_idx);
  assert.equal(stripRecommended(row.options[row.answer_idx].label), it.options[shownIdxOfAnswer].label);
});

test("project names are humanised without leaking the path", () => {
  assert.equal(humaniseProject("C--Users-someone-notes", [[/notes/i, "the notes folder"]]), "the notes folder");
  assert.equal(humaniseProject("C--Users-someone-garden-app"), "the app project");
  assert.ok(!/Users|someone/.test(humaniseProject("C--Users-someone-garden-app")));
});

// ---------- responses ----------

test("validateResponse accepts options, other and skips; rejects junk", () => {
  const ids = new Set(["a"]);
  assert.equal(validateResponse({ item_id: "a", answer_kind: "option", answer_idx: 1, confidence: 3 }, ids), null);
  assert.equal(validateResponse({ item_id: "a", answer_kind: "other", answer_text: "x", confidence: 5 }, ids), null);
  assert.equal(validateResponse({ item_id: "a", skipped: true }, ids), null);
  assert.ok(validateResponse({ item_id: "zzz", answer_idx: 0, confidence: 1 }, ids));
  assert.ok(validateResponse({ item_id: "a", answer_idx: 0, confidence: 9 }, ids));
  assert.ok(validateResponse({ item_id: "a", answer_idx: "0", confidence: 2 }, ids));
  assert.ok(validateResponse({ item_id: "a", answer_idx: 0, confidence: 2, events: "no" }, ids));
});

test("latestResponses: the last record per item wins", () => {
  const m = latestResponses([{ item_id: "a", answer_idx: 0 }, { item_id: "b", answer_idx: 1 }, { item_id: "a", answer_idx: 2 }]);
  assert.equal(m.get("a").answer_idx, 2);
  assert.equal(m.size, 2);
});

// ---------- server: save and resume ----------

test("server: items are blind, saves append, state resumes, partial restores, host check", async () => {
  const dir = tmp();
  const src = fixtureFile(dir);
  const app = createApp({ dataDir: join(dir, "data"), source: src, htmlPath: resolve(HERE, "..", "index.html") });
  const port = await listen(app, 0);
  const base = `http://127.0.0.1:${port}`;
  try {
    const html = await (await fetch(base + "/")).text();
    assert.ok(html.includes("<!doctype html>") && html.includes("Human LLM Council"));

    const items = await (await fetch(base + "/api/items")).json();
    assert.equal(items.items.length, 40);
    assert.ok(!JSON.stringify(items).match(/answer_idx|rec_idx|perm|recommend/i));

    let st = await (await fetch(base + "/api/state")).json();
    assert.equal(Object.keys(st.answered).length, 0);
    assert.equal(st.total, 40);

    const id0 = items.items[0].id;
    const id1 = items.items[1].id;
    let r = await fetch(base + "/api/save", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ item_id: id0, answer_kind: "option", answer_idx: 0, confidence: 4, events: [{ t: 1, type: "show" }] }) });
    assert.equal(r.status, 200);
    assert.equal((await r.json()).answered, 1);
    r = await fetch(base + "/api/save", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ item_id: id1, skipped: true }) });
    assert.equal(r.status, 200);

    // partial autosave for a third item, then state carries it
    const id2 = items.items[2].id;
    r = await fetch(base + "/api/partial", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ item_id: id2, answer_idx: 1, confidence: 2, comment: "half" }) });
    assert.equal(r.status, 200);
    st = await (await fetch(base + "/api/state")).json();
    assert.equal(Object.keys(st.answered).length, 2);
    assert.equal(st.answered[id1].skipped, true);
    assert.equal(st.answered[id0].skipped, false);
    assert.equal(st.partial.item_id, id2);
    assert.equal(st.partial.comment, "half");

    // saving that item clears the partial
    r = await fetch(base + "/api/save", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ item_id: id2, answer_kind: "option", answer_idx: 1, confidence: 2 }) });
    assert.equal(r.status, 200);
    st = await (await fetch(base + "/api/state")).json();
    assert.equal(st.partial, null);
    assert.equal(Object.keys(st.answered).length, 3);

    // the file has three lines; a second server over the same data dir resumes the same state
    const lines = readFileSync(app.files.responsesFile, "utf8").trim().split("\n");
    assert.equal(lines.length, 3);
    assert.ok(JSON.parse(lines[0]).server_received_at);
    const app2 = createApp({ dataDir: join(dir, "data"), source: src, htmlPath: resolve(HERE, "..", "index.html") });
    assert.equal(Object.keys(app2.state().answered).length, 3);
    assert.deepEqual(app2.items.map((i) => i.id), app.items.map((i) => i.id), "items.json is reused, not regenerated");

    // bad input
    r = await fetch(base + "/api/save", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ item_id: "nope", answer_idx: 0, confidence: 1 }) });
    assert.equal(r.status, 400);
    r = await fetch(base + "/api/save", { method: "POST", headers: { "content-type": "application/json" }, body: "{not json" });
    assert.equal(r.status, 400);
    r = await fetch(base + "/nowhere");
    assert.equal(r.status, 404);
    // fetch() will not override Host, so use a raw request for the DNS-rebinding guard.
    const status = await new Promise((ok, fail) => {
      const rq = http.request({ host: "127.0.0.1", port, path: "/api/items", method: "GET", headers: { host: "evil.example" } }, (res) => { res.resume(); ok(res.statusCode); });
      rq.on("error", fail);
      rq.end();
    });
    assert.equal(status, 403);
  } finally {
    app.server.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

// ---------- scorer ----------

test("kappa: perfect agreement is 1, systematic disagreement is below 0", () => {
  assert.equal(cohenKappa([[0, 0], [1, 1], [2, 2], [0, 0]]), 1);
  assert.ok(cohenKappa([[0, 1], [1, 0], [0, 1], [1, 0]]) < 0);
  assert.equal(cohenKappa([]), null);
});

test("scorer on fixtures: agreement, strata, confidence, think time, kappa, reweighting", () => {
  const rows = makeRows(120, 11);
  const { items, meta } = selectItems(rows, { n: 40, seed: "s" });
  // Build responses: agree on the first 30, disagree on 8, 'other' on 1, skip 1.
  const responses = [];
  items.forEach((it, i) => {
    const shownOfAnswer = it.perm.indexOf(it.answer_idx);
    if (i < 30) responses.push({ item_id: it.id, answer_kind: "option", answer_idx: shownOfAnswer, confidence: 1 + (i % 5), total_think_ms: 1000 + i * 500, considered: i % 4 === 0 ? [0, shownOfAnswer] : [shownOfAnswer], hover_dwell_ms: { [`option-${shownOfAnswer}`]: 3000, "option-0": 1000 } });
    else if (i < 38) responses.push({ item_id: it.id, answer_kind: "option", answer_idx: (shownOfAnswer + 1) % it.options.length, confidence: 2, total_think_ms: 20000, considered: [0] });
    else if (i === 38) responses.push({ item_id: it.id, answer_kind: "other", answer_text: "neither", confidence: 3, total_think_ms: 5000 });
    else responses.push({ item_id: it.id, skipped: true });
  });
  // A superseding re-answer for item 31 that now agrees.
  const it31 = items[31];
  responses.push({ item_id: it31.id, answer_kind: "option", answer_idx: it31.perm.indexOf(it31.answer_idx), confidence: 5, total_think_ms: 3000, considered: [1] });

  const s = score(items, responses, meta);
  assert.equal(s.items_total, 40);
  assert.equal(s.responded, 40);
  assert.equal(s.skipped, 1);
  assert.equal(s.answered_other, 1);
  assert.equal(s.answered_with_option, 38);
  assert.ok(Math.abs(s.agreement - 31 / 38) < 1e-9);
  assert.ok(s.agreement_ci95[0] < s.agreement && s.agreement < s.agreement_ci95[1]);
  assert.ok(s.cohen_kappa_pooled_positions > 0.5);
  assert.ok(s.chance_corrected_agreement_per_item > 0.5);
  const stratN = Object.values(s.by_stratum).reduce((a, b) => a + b.n, 0);
  assert.equal(stratN, 38);
  const confN = Object.values(s.by_confidence).reduce((a, b) => a + b.n, 0);
  assert.equal(confN, 38);
  assert.equal(s.by_think_time.fast.n + s.by_think_time.middle.n + s.by_think_time.slow.n, 38);
  assert.ok(s.by_think_time.slow.agreement < s.by_think_time.fast.agreement, "slow tertile holds the disagreements");
  assert.equal(s.changed_mind.n + s.did_not_change_mind.n, 38);
  assert.ok(s.agreement_reweighted_to_test_population !== null);
  assert.ok(s.dwell_ratio_chosen_vs_others.n >= 1 && s.dwell_ratio_chosen_vs_others.median > 1);

  const md = renderResults(s);
  assert.ok(md.includes("Agreement with the original choice") && md.includes("| override |"));
  assert.ok(!/case \d+/.test(md), "RESULTS.md must not contain question text");
});

test("score.mjs end to end on a fixture data dir, writes RESULTS.md", async () => {
  const dir = tmp();
  const src = fixtureFile(dir);
  const app = createApp({ dataDir: join(dir, "data"), source: src, htmlPath: resolve(HERE, "..", "index.html") });
  const port = await listen(app, 0);
  try {
    for (const it of app.items.slice(0, 5)) {
      await fetch(`http://127.0.0.1:${port}/api/save`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ item_id: it.id, answer_kind: "option", answer_idx: it.perm.indexOf(it.answer_idx), confidence: 4, total_think_ms: 2000 }) });
    }
    const { summary, out } = runScore({ dataDir: join(dir, "data") });
    assert.equal(summary.answered_with_option, 5);
    assert.equal(summary.agreement, 1);
    assert.ok(existsSync(out));
    assert.ok(readFileSync(out, "utf8").includes("100.0%"));
  } finally {
    app.server.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
