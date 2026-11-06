// GENERATED from martymcenroe/Palaestra by tools/export_exedra.py (#323). Do not edit it here: a change made here is overwritten by the next export and fails the drift test. Change it upstream, or open an issue with a scenario pack that shows the problem.

/**
 * Problem reports (#274): one POST, from a signed-in player only (#689).
 *
 * The operator takes no report from someone signed out (#689: "why wold i
 * ever take a report from someone signed out? i wouldn't!"). A visitor is
 * refused with the same 403 every gated player route gives, before the
 * limiter, the database or the mail is touched, so an anonymous caller costs
 * nothing. The form was open from #274 until #689; the client now shows a
 * visitor a sign-in link in its place.
 *
 * The trace, when attached, is the client's own ring buffer of recent API
 * errors and breadcrumbs — sent only because the reporter pressed send
 * with the attach box ticked. Contents are enumerated in the privacy
 * policy. Limits are hard caps, not validation niceties: a signed-in
 * player must not be able to turn this endpoint into a free write amplifier.
 *
 * Since #685 the caps bound volume as well as size:
 *
 * - Each player is held to REPORTS_PER_MINUTE by the SUPPORT_RATE_LIMITER
 *   binding (web/wrangler.jsonc), keyed by player id and never by address,
 *   so students sharing one campus address are each counted alone. The
 *   binding is approximate and counts per Cloudflare location, which is fine
 *   for a ceiling meant only to stop a script.
 * - The operator is mailed for the first MAIL_CEILING_PER_HOUR reports in a
 *   rolling hour, then once more with a digest, then not again until the
 *   hour's count falls back. Every report is still stored.
 * - Past TRACE_CEILING_PER_HOUR traced reports in a rolling hour, a report is
 *   stored without its trace, which is most of its size, and the reply says so.
 *
 * Without its limiter the form refuses with a 503 rather than run unlimited:
 * a missing binding is a misconfigured deploy, and failing open would hide it.
 */
import { Hono } from "hono";

import { ENGINE_VERSION } from "../shared/engine";
import { isAdminId } from "./admin";
import { notifyOperator, type OperatorMail } from "./notify";
import { currentPlayer } from "./session";

const MAX_MESSAGE = 2000;
const MAX_PAGE = 200;
const MAX_TRACE = 64 * 1024;

/** Reports per key per 60 s. The binding in web/wrangler.jsonc holds the same
 * number, and a test fails if the two disagree (#685). */
export const REPORTS_PER_MINUTE = 60;
/** Reports mailed one by one in a rolling hour before the digest (#685). */
export const MAIL_CEILING_PER_HOUR = 20;
/** Traced reports stored with their trace in a rolling hour (#685). */
export const TRACE_CEILING_PER_HOUR = 100;

const HOUR_MS = 3_600_000;

/** The limiter binding, typed here as auth.ts types its GitHub settings, so
 * the generated Env needs no regeneration (#685). */
type SupportEnv = Env & { SUPPORT_RATE_LIMITER?: RateLimit };

/** Whom a report counts against: always the player (#689). */
export function reportKey(playerId: string): string {
  return `player:${playerId}`;
}

export const support = new Hono<{ Bindings: Env }>();

function supportMail(message: string, page: string, playerId: string): OperatorMail {
  return {
    subject: `Support: ${message.slice(0, 60)}${message.length > 60 ? "…" : ""}`,
    lines: [
      `Page: ${page}`,
      `From: ${playerId}`,
      `Message: ${message}`,
      "Full report (and trace, if attached) is in support_reports.",
    ],
  };
}

function digestMail(count: number, page: string, playerId: string): OperatorMail {
  return {
    subject: `Support: more than ${MAIL_CEILING_PER_HOUR} reports in the last hour`,
    lines: [
      `${count} support reports have arrived in the last hour.`,
      `Every report is still stored in support_reports; no more mail is sent for each one until the hour's count falls back to ${MAIL_CEILING_PER_HOUR} or fewer.`,
      `Latest: page ${page}, from ${playerId}.`,
    ],
  };
}

/** The mail a report earns, given how many reports the rolling hour now holds
 * including it: one each up to the ceiling, one digest just past it, then none. */
function mailFor(
  count: number,
  message: string,
  page: string,
  playerId: string,
): OperatorMail | null {
  if (count <= MAIL_CEILING_PER_HOUR) return supportMail(message, page, playerId);
  if (count === MAIL_CEILING_PER_HOUR + 1) return digestMail(count, page, playerId);
  return null;
}

support.post("/api/support", async (c) => {
  // The session comes first (#689): a visitor is refused before the limiter,
  // the database or the mail is touched, and a misconfigured deploy cannot
  // turn that refusal into a 503.
  const playerId = await currentPlayer(c);
  if (!playerId)
    return c.json({ error: "sign in to report a problem", code: "NO_SESSION" }, 403);

  const limiter = (c.env as SupportEnv).SUPPORT_RATE_LIMITER;
  if (!limiter) {
    console.error(
      JSON.stringify({ level: "error", message: "support rate limiter is not bound", binding: "SUPPORT_RATE_LIMITER" }),
    );
    return c.json(
      { error: "support reports are unavailable: the rate limiter is not configured", code: "SUPPORT_LIMIT_UNCONFIGURED" },
      503,
    );
  }

  const key = reportKey(playerId);
  let allowed: boolean;
  try {
    ({ success: allowed } = await limiter.limit({ key }));
  } catch (e: unknown) {
    console.error(
      JSON.stringify({ level: "error", message: "support rate limiter failed", detail: String(e) }),
    );
    return c.json(
      { error: "support reports are unavailable: the rate limiter failed", code: "SUPPORT_LIMIT_FAILED" },
      503,
    );
  }
  if (!allowed) {
    c.header("Retry-After", "60");
    return c.json(
      { error: "too many reports from you in the last minute; try again in a minute", code: "RATE_LIMITED" },
      429,
    );
  }

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

  const now = new Date();
  const since = new Date(now.getTime() - HOUR_MS).toISOString();
  let keepTrace = trace !== null;
  if (keepTrace) {
    const traced = await c.env.DB.prepare(
      "SELECT COUNT(*) AS n FROM support_reports WHERE created_at > ? AND trace_json IS NOT NULL",
    )
      .bind(since)
      .first<{ n: number }>();
    keepTrace = Number(traced?.n ?? 0) < TRACE_CEILING_PER_HOUR;
  }

  const id = crypto.randomUUID();
  // One batch is one transaction, so the count includes this report and no
  // two reports can both see the count that earns the digest.
  const [, counted] = await c.env.DB.batch<{ n: number }>([
    c.env.DB.prepare(
      `INSERT INTO support_reports (id, player_id, page, message, engine_version, trace_json, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    ).bind(id, playerId, page, message, ENGINE_VERSION, keepTrace ? trace : null, now.toISOString()),
    c.env.DB.prepare("SELECT COUNT(*) AS n FROM support_reports WHERE created_at > ?").bind(since),
  ]);

  const mail = mailFor(Number(counted?.results?.[0]?.n ?? 0), message, page, playerId);
  if (mail) notifyOperator(c.env, c.executionCtx, mail);
  return c.json({
    ok: true,
    report_id: id,
    ...(trace !== null && !keepTrace ? { trace_kept: false } : {}),
  });
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
  // Stamp the closing time, and clear it on reopening. This existed because a
  // retention clock counted from it (#400); that clock is gone (#414) and the
  // stamp is kept on its own merits — "when was this dealt with", and the
  // difference between a report closed once and one that had to be reopened,
  // are things the support workflow wants to know.
  const res = await c.env.DB.prepare(
    "UPDATE support_reports SET status = ?, closed_at = ? WHERE id = ?",
  )
    .bind(status, status === "closed" ? new Date().toISOString() : null, c.req.param("id"))
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
