#!/usr/bin/env node
// Tiny std-lib server for the retest. Binds 127.0.0.1 only. Serves index.html, the client view of the items
// (no answers, no recommendation, no permutation), and appends each response to responses.jsonl.
//
//   node server.mjs [--port 4421] [--data-dir <dir>] [--source <frozen jsonl>] [--items <items.json>]
//   env: RETEST_PORT, RETEST_DATA_DIR, RETEST_SOURCE, RETEST_ITEMS
//
// Prints only the URL and counts. Never a row's text.

import { createServer } from "node:http";
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { clientView, latestResponses, validateResponse } from "./lib.mjs";
import { buildItems, DEFAULT_DATA_DIR, DEFAULT_SOURCE, readJsonl } from "./select.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const MAX_BODY = 256 * 1024;

function args(argv) {
  const o = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) o[a.slice(2)] = argv[++i];
  }
  return o;
}

export function createApp({ dataDir = DEFAULT_DATA_DIR, source = DEFAULT_SOURCE, itemsPath, htmlPath = resolve(HERE, "index.html") } = {}) {
  mkdirSync(dataDir, { recursive: true });
  const itemsFile = itemsPath || resolve(dataDir, "items.json");
  const responsesFile = resolve(dataDir, "responses.jsonl");
  const partialFile = resolve(dataDir, "partial.json");
  const built = buildItems({ source, out: itemsFile });
  const items = built.items;
  const meta = built.meta;
  const itemIds = new Set(items.map((it) => it.id));
  const views = items.map(clientView);

  function readResponses() {
    return existsSync(responsesFile) ? readJsonl(responsesFile) : [];
  }

  function state() {
    const latest = latestResponses(readResponses());
    const answered = {};
    for (const [id, r] of latest) answered[id] = { skipped: Boolean(r.skipped), at: r.server_received_at || r.submitted_at || null };
    let partial = null;
    if (existsSync(partialFile)) {
      try {
        partial = JSON.parse(readFileSync(partialFile, "utf8"));
      } catch {
        partial = null;
      }
    }
    return { total: items.length, answered, partial };
  }

  function json(res, code, obj) {
    const body = JSON.stringify(obj);
    res.writeHead(code, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "content-length": Buffer.byteLength(body) });
    res.end(body);
  }

  function readBody(req) {
    return new Promise((ok, fail) => {
      const chunks = [];
      let size = 0;
      req.on("data", (c) => {
        size += c.length;
        if (size > MAX_BODY) {
          fail(new Error("body too large"));
          req.destroy();
          return;
        }
        chunks.push(c);
      });
      req.on("end", () => ok(Buffer.concat(chunks).toString("utf8")));
      req.on("error", fail);
    });
  }

  function hostOk(req) {
    const h = String(req.headers.host || "").toLowerCase();
    return /^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/.test(h);
  }

  async function handle(req, res) {
    if (!hostOk(req)) return json(res, 403, { error: "forbidden host" });
    const url = new URL(req.url, "http://127.0.0.1");
    const p = url.pathname;
    try {
      if (req.method === "GET" && (p === "/" || p === "/index.html")) {
        const html = readFileSync(htmlPath, "utf8");
        res.writeHead(200, {
          "content-type": "text/html; charset=utf-8",
          "cache-control": "no-store",
          "content-security-policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; form-action 'none'; base-uri 'none'",
          "x-content-type-options": "nosniff",
          "referrer-policy": "no-referrer",
        });
        return res.end(html);
      }
      if (req.method === "GET" && p === "/api/items") return json(res, 200, { items: views, meta: { n: items.length, seed: meta.seed } });
      if (req.method === "GET" && p === "/api/state") return json(res, 200, state());
      if (req.method === "POST" && (p === "/api/save" || p === "/save")) {
        const raw = await readBody(req);
        let body;
        try {
          body = JSON.parse(raw);
        } catch {
          return json(res, 400, { error: "invalid json" });
        }
        const err = validateResponse(body, itemIds);
        if (err) return json(res, 400, { error: err });
        body.server_received_at = new Date().toISOString();
        appendFileSync(responsesFile, JSON.stringify(body) + "\n", "utf8");
        if (existsSync(partialFile)) {
          try {
            const part = JSON.parse(readFileSync(partialFile, "utf8"));
            if (part && part.item_id === body.item_id) unlinkSync(partialFile);
          } catch {
            /* ignore */
          }
        }
        const st = state();
        return json(res, 200, { ok: true, answered: Object.keys(st.answered).length, total: st.total });
      }
      if (req.method === "POST" && p === "/api/partial") {
        const raw = await readBody(req);
        let body;
        try {
          body = JSON.parse(raw);
        } catch {
          return json(res, 400, { error: "invalid json" });
        }
        if (!body || typeof body.item_id !== "string" || !itemIds.has(body.item_id)) return json(res, 400, { error: "unknown item_id" });
        body.server_received_at = new Date().toISOString();
        const tmp = partialFile + ".tmp";
        writeFileSync(tmp, JSON.stringify(body), "utf8");
        renameSync(tmp, partialFile);
        return json(res, 200, { ok: true });
      }
      return json(res, 404, { error: "not found" });
    } catch (e) {
      return json(res, e.message === "body too large" ? 413 : 500, { error: e.message === "body too large" ? "body too large" : "server error" });
    }
  }

  const server = createServer((req, res) => {
    handle(req, res).catch(() => {
      try {
        json(res, 500, { error: "server error" });
      } catch {
        /* closed */
      }
    });
  });
  return { server, items, meta, files: { itemsFile, responsesFile, partialFile }, state };
}

export function listen(app, port = 4421) {
  return new Promise((ok, fail) => {
    app.server.once("error", fail);
    app.server.listen(port, "127.0.0.1", () => ok(app.server.address().port));
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const a = args(process.argv.slice(2));
  const port = Number(a.port || process.env.RETEST_PORT || 4421);
  const dataDir = resolve(a["data-dir"] || process.env.RETEST_DATA_DIR || DEFAULT_DATA_DIR);
  const source = resolve(a.source || process.env.RETEST_SOURCE || DEFAULT_SOURCE);
  const itemsPath = a.items || process.env.RETEST_ITEMS ? resolve(a.items || process.env.RETEST_ITEMS) : undefined;
  const app = createApp({ dataDir, source, itemsPath });
  listen(app, port)
    .then((p) => {
      const st = app.state();
      console.log(`retest server on http://127.0.0.1:${p}/  items=${app.items.length} answered=${Object.keys(st.answered).length} data=${dataDir}`);
    })
    .catch((e) => {
      console.error(`could not listen on 127.0.0.1:${port}: ${e.code || e.message}`);
      process.exit(2);
    });
}
