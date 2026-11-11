// Pure functions for the self-consistency retest (U2). No I/O here, so every function is unit-testable on fixtures.
//
// Selection: 40 held-out rulings from the frozen test split, deterministic for a given seed, stratified by whether
// he overrode Claude's recommendation (override), followed it (follow) or no option was marked (norec).
// Presentation: the "(Recommended)" marker is removed and the options are shuffled per item (permutation recorded).
// Scoring: agreement between his original choice and his retest choice, by stratum, confidence and think time,
// plus Cohen's kappa and a per-item chance-corrected agreement.

// ---------- text ----------

// Widened from council_eval.ingest.strip_recommended: parenthesised markers with trailing words, and leading
// "Recommended:" forms in descriptions (U9 found 5 of 375 test prompts still carrying a cue after the narrow regex).
const REC_PAREN = /\s*[\(\[]\s*(?:strongly\s+)?recommended\b[^)\]]*[\)\]]\s*/gi;
const REC_LEAD = /^\s*(?:strongly\s+)?recommended\b\s*(?:option|choice|pick)?\s*[:\-–—.]\s*/i;
const REC_TAIL = /\s*[-–—:,]\s*(?:strongly\s+)?recommended\s*[.!]?\s*$/i;

export function stripRecommended(s) {
  if (!s) return "";
  return String(s).replace(REC_PAREN, " ").replace(REC_LEAD, "").replace(REC_TAIL, "").replace(/\s{2,}/g, " ").trim();
}

export function hasRecommendCue(s) {
  return /recommend/i.test(s || "");
}

export function rowHasCue(row) {
  const parts = [row.question, row.header, ...row.options.flatMap((o) => [o.label, o.description])];
  return parts.some((p) => hasRecommendCue(stripRecommended(p)));
}

// ---------- deterministic randomness ----------

function fnv1a(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

export function prng(seedStr) {
  let a = fnv1a(String(seedStr)) || 1;
  return function next() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function shuffledIndices(n, seedStr) {
  const rand = prng(seedStr);
  const perm = Array.from({ length: n }, (_, i) => i);
  for (let i = n - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [perm[i], perm[j]] = [perm[j], perm[i]];
  }
  return perm; // perm[newIndex] = oldIndex
}

// ---------- strata and selection ----------

export function stratum(row) {
  if (row.rec_idx === null || row.rec_idx === undefined) return "norec";
  return row.answer_idx === row.rec_idx ? "follow" : "override";
}

export const DEFAULT_QUOTAS = { override: 12, follow: 20, norec: 8 };

/**
 * Pick `n` rows deterministically. Rows that still carry a "recommend" cue after stripping are excluded, so the
 * retest shows no hint of what Claude preferred. Each stratum is sorted by a hash of (seed, id) and the quota taken;
 * a short stratum is topped up from the others in the same order. The final order interleaves strata.
 */
export function selectItems(rows, { n = 40, seed = "retest-2026-11-10", quotas = DEFAULT_QUOTAS } = {}) {
  const scorable = rows.filter((r) => r.answer_kind === "option" && Number.isInteger(r.answer_idx) && r.options.length >= 2);
  const clean = scorable.filter((r) => !rowHasCue(r));
  const excludedForCue = scorable.length - clean.length;
  const byStratum = { override: [], follow: [], norec: [] };
  for (const r of clean) byStratum[stratum(r)].push(r);
  const rank = (r) => fnv1a(`${seed}:${r.id}`);
  for (const k of Object.keys(byStratum)) byStratum[k].sort((a, b) => rank(a) - rank(b) || (a.id < b.id ? -1 : 1));

  const picked = [];
  const pickedIds = new Set();
  const want = { ...quotas };
  const total = Object.values(want).reduce((s, v) => s + v, 0);
  if (total !== n) {
    // Scale quotas to n, keeping the override share (the number that matters most).
    for (const k of Object.keys(want)) want[k] = Math.round((quotas[k] / total) * n);
    let diff = n - Object.values(want).reduce((s, v) => s + v, 0);
    want.follow += diff;
  }
  for (const k of Object.keys(want)) {
    for (const r of byStratum[k].slice(0, want[k])) {
      picked.push(r);
      pickedIds.add(r.id);
    }
  }
  if (picked.length < n) {
    const rest = clean.filter((r) => !pickedIds.has(r.id)).sort((a, b) => rank(a) - rank(b));
    for (const r of rest.slice(0, n - picked.length)) picked.push(r);
  }
  const order = shuffledIndices(picked.length, `${seed}:order`);
  const items = order.map((i) => picked[i]).map((r, pos) => prepareItem(r, seed, pos));
  const population = { override: 0, follow: 0, norec: 0 };
  for (const r of scorable) population[stratum(r)]++;
  return {
    items,
    meta: {
      seed,
      n: items.length,
      quotas: want,
      excluded_for_cue: excludedForCue,
      population,
      strata: items.reduce((m, it) => ((m[it.stratum] = (m[it.stratum] || 0) + 1), m), {}),
    },
  };
}

// ---------- presentation ----------

// Friendly names for project folders, e.g. [[/notes/i, "the notes folder"]]. Empty in the public
// code; the owner passes his own at run time so no folder name is published.
export const PROJECT_NAMES = [];

export function humaniseProject(project, names = PROJECT_NAMES) {
  for (const [re, name] of names) if (re.test(project || "")) return name;
  const tail = String(project || "").split(/--|-/).filter(Boolean).pop();
  return tail ? `the ${tail} project` : "a project";
}

export function contextLine(row) {
  let when = "";
  try {
    const d = new Date(row.ts);
    const day = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Singapore" }).format(d);
    const time = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Singapore" }).format(d);
    when = `${day}, ${time}`;
  } catch {
    when = String(row.ts || "").slice(0, 10);
  }
  const n = row.options.length;
  return `Asked in a Claude Code session in ${humaniseProject(row.project)} on ${when} (Singapore time). ${n} options were offered.`;
}

export function prepareItem(row, seed, position) {
  const perm = shuffledIndices(row.options.length, `${seed}:${row.id}`);
  return {
    id: row.id,
    position,
    ts: row.ts,
    project: row.project,
    header: stripRecommended(row.header),
    question: stripRecommended(row.question),
    context: contextLine(row),
    options: perm.map((old) => ({
      label: stripRecommended(row.options[old].label),
      description: stripRecommended(row.options[old].description),
    })),
    perm, // perm[shown] = original index
    answer_idx: row.answer_idx,
    rec_idx: row.rec_idx ?? null,
    stratum: stratum(row),
  };
}

// What the browser receives: never the answer, the recommendation or the permutation.
export function clientView(item) {
  const { id, position, header, question, context, options } = item;
  return { id, position, header, question, context, options: options.map((o) => ({ ...o })) };
}

// ---------- responses and scoring ----------

export function validateResponse(body, itemIds) {
  if (!body || typeof body !== "object") return "body must be an object";
  if (typeof body.item_id !== "string" || !itemIds.has(body.item_id)) return "unknown item_id";
  if (body.skipped !== true) {
    const isOther = body.answer_kind === "other";
    if (!isOther && !Number.isInteger(body.answer_idx)) return "answer_idx must be an integer unless skipped or other";
    if (isOther && typeof body.answer_text !== "string") return "other needs answer_text";
    if (!(Number.isInteger(body.confidence) && body.confidence >= 1 && body.confidence <= 5)) return "confidence must be 1..5";
  }
  if (body.events !== undefined && !Array.isArray(body.events)) return "events must be an array";
  return null;
}

// Last response per item wins (a re-answer after a resume supersedes).
export function latestResponses(lines) {
  const map = new Map();
  for (const r of lines) if (r && typeof r.item_id === "string") map.set(r.item_id, r);
  return map;
}

export function cohenKappa(pairs) {
  // pairs: [[a, b], ...] categorical labels. Pooled over option positions.
  const n = pairs.length;
  if (!n) return null;
  const cats = new Set();
  for (const [a, b] of pairs) {
    cats.add(a);
    cats.add(b);
  }
  let agree = 0;
  const ca = {};
  const cb = {};
  for (const [a, b] of pairs) {
    if (a === b) agree++;
    ca[a] = (ca[a] || 0) + 1;
    cb[b] = (cb[b] || 0) + 1;
  }
  const po = agree / n;
  let pe = 0;
  for (const c of cats) pe += ((ca[c] || 0) / n) * ((cb[c] || 0) / n);
  if (pe === 1) return 1;
  return (po - pe) / (1 - pe);
}

function mean(xs) {
  return xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null;
}

function median(xs) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function wilson(k, n, z = 1.96) {
  if (!n) return [0, 0];
  const p = k / n;
  const d = 1 + (z * z) / n;
  const c = (p + (z * z) / (2 * n)) / d;
  const h = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return [Math.max(0, c - h), Math.min(1, c + h)];
}

function rate(k, n) {
  return n ? k / n : null;
}

/**
 * Score responses against items. Returns aggregate numbers only; no row text.
 */
export function score(items, responseLines, meta = {}) {
  const byId = new Map(items.map((it) => [it.id, it]));
  const latest = latestResponses(responseLines);
  const rows = [];
  let skipped = 0;
  let other = 0;
  for (const [id, r] of latest) {
    const it = byId.get(id);
    if (!it) continue;
    if (r.skipped) {
      skipped++;
      continue;
    }
    if (r.answer_kind === "other") {
      other++;
      rows.push({ it, r, orig: null, agree: false, other: true });
      continue;
    }
    const orig = it.perm[r.answer_idx];
    rows.push({ it, r, orig, agree: orig === it.answer_idx, other: false });
  }
  const answered = rows.filter((x) => !x.other);
  const nAll = rows.length;
  const nAns = answered.length;
  const agreeK = answered.filter((x) => x.agree).length;

  const byStratum = {};
  for (const s of ["override", "follow", "norec"]) {
    const xs = answered.filter((x) => x.it.stratum === s);
    byStratum[s] = { n: xs.length, agreement: rate(xs.filter((x) => x.agree).length, xs.length) };
  }
  // Reweight to the test population so the oversampled override stratum does not distort the headline.
  let reweighted = null;
  if (meta.population) {
    const popN = Object.values(meta.population).reduce((s, v) => s + v, 0);
    let acc = 0;
    let wsum = 0;
    for (const s of Object.keys(byStratum)) {
      if (byStratum[s].n && meta.population[s]) {
        const w = meta.population[s] / popN;
        acc += w * byStratum[s].agreement;
        wsum += w;
      }
    }
    reweighted = wsum ? acc / wsum : null;
  }

  const byConfidence = {};
  for (let c = 1; c <= 5; c++) {
    const xs = answered.filter((x) => x.r.confidence === c);
    byConfidence[c] = { n: xs.length, agreement: rate(xs.filter((x) => x.agree).length, xs.length) };
  }

  const think = answered.map((x) => Number(x.r.total_think_ms) || 0);
  const sortedThink = [...think].sort((a, b) => a - b);
  const t1 = sortedThink[Math.floor(sortedThink.length / 3)] ?? 0;
  const t2 = sortedThink[Math.floor((2 * sortedThink.length) / 3)] ?? 0;
  const tert = { fast: [], middle: [], slow: [] };
  for (const x of answered) {
    const t = Number(x.r.total_think_ms) || 0;
    (t < t1 ? tert.fast : t < t2 ? tert.middle : tert.slow).push(x);
  }
  const byThinkTime = {};
  for (const k of Object.keys(tert)) byThinkTime[k] = { n: tert[k].length, agreement: rate(tert[k].filter((x) => x.agree).length, tert[k].length) };

  const changed = answered.filter((x) => Array.isArray(x.r.considered) && new Set(x.r.considered).size > 1);
  const unchanged = answered.filter((x) => !(Array.isArray(x.r.considered) && new Set(x.r.considered).size > 1));

  const pairs = answered.map((x) => [x.it.answer_idx, x.orig]);
  const kappa = cohenKappa(pairs);
  const pe = nAns ? mean(answered.map((x) => 1 / x.it.options.length)) : null;
  const po = rate(agreeK, nAns);
  const chanceCorrected = nAns && pe !== null && pe < 1 ? (po - pe) / (1 - pe) : null;

  // Where the retest disagreed: did he move towards or away from Claude's recommendation?
  const dis = answered.filter((x) => !x.agree && x.it.rec_idx !== null);
  const movedToRec = dis.filter((x) => x.orig === x.it.rec_idx).length;
  const movedOffRec = dis.filter((x) => x.it.answer_idx === x.it.rec_idx).length;

  // Hover: dwell on the final choice versus the mean dwell on the others.
  const dwellRatio = [];
  for (const x of answered) {
    const h = x.r.hover_dwell_ms || {};
    const chosen = Number(h[`option-${x.r.answer_idx}`]) || 0;
    const others = x.it.options.map((_, i) => i).filter((i) => i !== x.r.answer_idx).map((i) => Number(h[`option-${i}`]) || 0);
    const mo = mean(others);
    if (mo !== null && mo > 0) dwellRatio.push(chosen / mo);
  }

  const [lo, hi] = wilson(agreeK, nAns);
  return {
    items_total: items.length,
    responded: nAll + skipped,
    answered_with_option: nAns,
    answered_other: other,
    skipped,
    agreement: po,
    agreement_ci95: [lo, hi],
    agreement_reweighted_to_test_population: reweighted,
    cohen_kappa_pooled_positions: kappa,
    chance_corrected_agreement_per_item: chanceCorrected,
    expected_chance_agreement: pe,
    by_stratum: byStratum,
    by_confidence: byConfidence,
    by_think_time: { ...byThinkTime, tertile_cuts_ms: [t1, t2] },
    changed_mind: { n: changed.length, agreement: rate(changed.filter((x) => x.agree).length, changed.length) },
    did_not_change_mind: { n: unchanged.length, agreement: rate(unchanged.filter((x) => x.agree).length, unchanged.length) },
    disagreements_with_a_recommendation: { n: dis.length, moved_towards_recommendation: movedToRec, moved_away_from_recommendation: movedOffRec },
    think_time_ms: { mean: mean(think), median: median(think) },
    first_interaction_ms: { median: median(answered.map((x) => Number(x.r.first_interaction_ms)).filter((v) => Number.isFinite(v))) },
    dwell_ratio_chosen_vs_others: { n: dwellRatio.length, median: median(dwellRatio) },
    comments: rows.filter((x) => typeof x.r.comment === "string" && x.r.comment.trim()).length,
  };
}

function pct(v) {
  return v === null || v === undefined || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(1)}%`;
}

function ms(v) {
  return v === null || v === undefined ? "—" : `${(v / 1000).toFixed(1)} s`;
}

export function renderResults(s, { title = "Self-consistency retest: results" } = {}) {
  const L = [];
  L.push(`# ${title}`, "");
  L.push(`Local only (build/local is git-ignored). Aggregates; no question text.`, "");
  L.push(`| Measure | Value |`, `|---|---|`);
  L.push(`| Items | ${s.items_total} |`);
  L.push(`| Responded | ${s.responded} (answered with an option ${s.answered_with_option}, "Other" ${s.answered_other}, skipped ${s.skipped}) |`);
  L.push(`| **Agreement with his original choice** | **${pct(s.agreement)}** (Wilson 95% ${pct(s.agreement_ci95[0])} to ${pct(s.agreement_ci95[1])}) |`);
  L.push(`| Agreement reweighted to the test population | ${pct(s.agreement_reweighted_to_test_population)} |`);
  L.push(`| Cohen's kappa (pooled option positions) | ${s.cohen_kappa_pooled_positions === null ? "—" : s.cohen_kappa_pooled_positions.toFixed(3)} |`);
  L.push(`| Chance-corrected agreement (per-item uniform chance ${pct(s.expected_chance_agreement)}) | ${s.chance_corrected_agreement_per_item === null ? "—" : s.chance_corrected_agreement_per_item.toFixed(3)} |`);
  L.push(`| Think time | mean ${ms(s.think_time_ms.mean)}, median ${ms(s.think_time_ms.median)} |`);
  L.push(`| First interaction | median ${ms(s.first_interaction_ms.median)} |`);
  L.push(`| Dwell on the chosen option vs the others | median ratio ${s.dwell_ratio_chosen_vs_others.median === null ? "—" : s.dwell_ratio_chosen_vs_others.median.toFixed(2)} (n=${s.dwell_ratio_chosen_vs_others.n}) |`);
  L.push(`| Notes left | ${s.comments} |`, "");
  L.push(`## By stratum`, "", `| Stratum | n | Agreement |`, `|---|---|---|`);
  for (const k of ["override", "follow", "norec"]) L.push(`| ${k} | ${s.by_stratum[k].n} | ${pct(s.by_stratum[k].agreement)} |`);
  L.push("", `## By confidence (1 = a guess, 5 = certain)`, "", `| Confidence | n | Agreement |`, `|---|---|---|`);
  for (let c = 1; c <= 5; c++) L.push(`| ${c} | ${s.by_confidence[c].n} | ${pct(s.by_confidence[c].agreement)} |`);
  L.push("", `## By think time (tertiles; cuts at ${ms(s.by_think_time.tertile_cuts_ms[0])} and ${ms(s.by_think_time.tertile_cuts_ms[1])})`, "", `| Tertile | n | Agreement |`, `|---|---|---|`);
  for (const k of ["fast", "middle", "slow"]) L.push(`| ${k} | ${s.by_think_time[k].n} | ${pct(s.by_think_time[k].agreement)} |`);
  L.push("", `## Changing his mind`, "", `| Group | n | Agreement |`, `|---|---|---|`);
  L.push(`| Clicked more than one option before Next | ${s.changed_mind.n} | ${pct(s.changed_mind.agreement)} |`);
  L.push(`| Clicked one option only | ${s.did_not_change_mind.n} | ${pct(s.did_not_change_mind.agreement)} |`);
  const d = s.disagreements_with_a_recommendation;
  L.push("", `## Disagreements on items that had a recommendation`, "");
  L.push(`${d.n} disagreements; ${d.moved_towards_recommendation} moved towards what Claude had recommended, ${d.moved_away_from_recommendation} moved away from it.`, "");
  L.push(`## Reading it`, "");
  L.push(`Agreement is the ceiling for any Scrutiniser arm: a model scoring above it on the same rows is fitting noise. Kappa below 0.4 means the retest barely beats chance; above 0.6 is substantial self-consistency.`);
  return L.join("\n") + "\n";
}
