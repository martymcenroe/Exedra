/**
 * Problem reports (#274): one POST, no auth required.
 *
 * Signed-out reporting is the point — the founding incident (#273) was a
 * signed-out 403, filed by exactly the person an authenticated-only form
 * would have turned away. A session, when present, attaches the player id
 * so the operator can answer; absent, the report still lands.
 *
 * The trace, when attached, is the client's own ring buffer of recent API
 * errors and breadcrumbs — sent only because the reporter pressed send
 * with the attach box ticked. Contents are enumerated in the privacy
 * policy. Limits are hard caps, not validation niceties: this endpoint is
 * unauthenticated and must not be a free write amplifier.
 */
import { Hono } from "hono";

import { ENGINE_VERSION } from "../shared/engine";
import { isAdminId } from "./admin";
import { notifyOperator, type OperatorMail } from "./notify";
import { currentPlayer } from "./session";

const MAX_MESSAGE = 2000;
const MAX_PAGE = 200;
const MAX_TRACE = 64 * 1024;

export const support = new Hono<{ Bindings: Env }>();

function supportMail(message: string, page: string, playerId: string | null): OperatorMail {
  return {
    subject: `Support: ${message.slice(0, 60)}${message.length > 60 ? "…" : ""}`,
    lines: [
      `Page: ${page}`,
      `From: ${playerId ?? "signed out"}`,
      `Message: ${message}`,
      "Full report (and trace, if attached) is in support_reports.",
    ],
  };
}

support.post("/api/support", async (c) => {
  const body = await c.req
    .json<{ message?: string; page?: string; trace?: unknown }>()
    .catch(() => null);
  const message = body?.message?.trim();
  if (!message || message.length > MAX_MESSAGE)
    return c.json({ error: "message required (max 2000 chars)", code: "BAD_REQUEST" }, 400);
  const page = (body?.page ?? "unknown").slice(0, MAX_PAGE);
  const trace = body?.trace != null ? JSON.stringify(body.trace) : null;
  if (trace && trace.length > MAX_TRACE)
    return c.json({ error: "trace too large", code: "BAD_REQUEST" }, 400);

  const playerId = await currentPlayer(c);
  const id = crypto.randomUUID();
  await c.env.DB.prepare(
    `INSERT INTO support_reports (id, player_id, page, message, engine_version, trace_json, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(id, playerId, page, message, ENGINE_VERSION, trace, new Date().toISOString())
    .run();

  notifyOperator(c.env, c.executionCtx, supportMail(message, page, playerId));
  return c.json({ ok: true, report_id: id });
});

// --- The operator's triage surface (#275) and the reporter's receipt -------
//
// Admin endpoints follow the #116 rules verbatim: fail closed as a 404
// indistinguishable from no-route, allowlist from wrangler vars only.
// Replies to reporters wait on a player-capable mail transport; until then
// triage is list, read, close — and the reporter can see their report's
// status on their own profile instead of emailing again.

support.get("/api/admin/support", async (c) => {
  const admin = isAdminId(c.env, await currentPlayer(c));
  if (!admin) return c.json({ error: "no such endpoint", code: "NOT_FOUND" }, 404);
  const { results } = await c.env.DB.prepare(
    `SELECT s.id, s.player_id, p.display_name, s.page, s.message, s.engine_version,
            s.trace_json IS NOT NULL AS has_trace, s.created_at, s.status
       FROM support_reports s LEFT JOIN players p ON p.id = s.player_id
      ORDER BY s.created_at DESC LIMIT 200`,
  ).all();
  return c.json({ reports: results });
});

support.get("/api/admin/support/:id", async (c) => {
  const admin = isAdminId(c.env, await currentPlayer(c));
  if (!admin) return c.json({ error: "no such endpoint", code: "NOT_FOUND" }, 404);
  const row = await c.env.DB.prepare("SELECT * FROM support_reports WHERE id = ?")
    .bind(c.req.param("id"))
    .first();
  if (!row) return c.json({ error: "no such report", code: "NOT_FOUND" }, 404);
  return c.json({ report: row });
});

support.post("/api/admin/support/:id/status", async (c) => {
  const admin = isAdminId(c.env, await currentPlayer(c));
  if (!admin) return c.json({ error: "no such endpoint", code: "NOT_FOUND" }, 404);
  const body = await c.req.json<{ status?: string }>().catch(() => null);
  const status = body?.status;
  if (status !== "new" && status !== "open" && status !== "closed")
    return c.json({ error: "status must be new, open, or closed", code: "BAD_REQUEST" }, 400);
  const res = await c.env.DB.prepare("UPDATE support_reports SET status = ? WHERE id = ?")
    .bind(status, c.req.param("id"))
    .run();
  if (res.meta.changes === 0)
    return c.json({ error: "no such report", code: "NOT_FOUND" }, 404);
  return c.json({ ok: true, status });
});

/** The reporter's own receipts: message, when, and where it stands. */
support.get("/api/me/support", async (c) => {
  const playerId = await currentPlayer(c);
  if (!playerId) return c.json({ error: "no player session", code: "NO_SESSION" }, 403);
  const { results } = await c.env.DB.prepare(
    `SELECT id, page, message, created_at, status FROM support_reports
      WHERE player_id = ? ORDER BY created_at DESC LIMIT 50`,
  )
    .bind(playerId)
    .all();
  return c.json({ reports: results });
});
