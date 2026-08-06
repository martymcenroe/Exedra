/**
 * Sign In with LinkedIn using OpenID Connect (#31), per 0013 §2.5:
 * `sub` is the stable key from day one (vanityName needs restricted APIs),
 * player ids are provider-prefixed (`linkedin:<sub>`), and provider tokens
 * are exchanged for our own session cookie then DISCARDED — never stored
 * (0013 §2.7).
 *
 * As of 2026-07-27 LinkedIn IS the gate: guest play is disabled by operator
 * directive, so this is the only way to obtain a session. Existing guest rows
 * keep their history and their profile, but no new ones are minted. If
 * LinkedIn isn't configured the endpoints fail closed with AUTH_UNCONFIGURED
 * — which now means nobody can start a run, so it is a hard outage, not a
 * degraded mode.
 */

import { Hono } from "hono";
import { deleteCookie, getCookie, setCookie } from "hono/cookie";

import { isAdminId, recordLogin } from "./admin";
import { newPlayerMail, notifyOperator } from "./notify";
import { SESSION_COOKIE, signSession, verifySession } from "./session";

const AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization";
const TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken";
const USERINFO_URL = "https://api.linkedin.com/v2/userinfo";
const STATE_COOKIE = "palaestra_oauth_state";
const RETURN_COOKIE = "palaestra_oauth_return";

export const auth = new Hono<{ Bindings: Env }>();

function linkedinConfigured(env: Env): boolean {
  return Boolean(env.LINKEDIN_CLIENT_ID && env.LINKEDIN_CLIENT_SECRET);
}

function callbackUrl(reqUrl: string): string {
  const u = new URL(reqUrl);
  return `${u.origin}/api/auth/callback`;
}

auth.get("/api/auth/me", async (c) => {
  const available = linkedinConfigured(c.env);
  const token = getCookie(c, SESSION_COOKIE);
  if (!token) return c.json({ player: null, linkedin_available: available });
  const playerId = await verifySession(token, c.env.SESSION_SECRET);
  if (!playerId) return c.json({ player: null, linkedin_available: available });
  const row = await c.env.DB.prepare(
    "SELECT id, kind, display_name, leaderboard_opt_out FROM players WHERE id = ?",
  )
    .bind(playerId)
    .first<{
      id: string;
      kind: string;
      display_name: string | null;
      leaderboard_opt_out: number;
    }>();
  if (!row) return c.json({ player: null, linkedin_available: available });
  return c.json({
    player: {
      id: row.id,
      display_name: row.display_name,
      provider: row.id.startsWith("linkedin:") ? "linkedin" : "guest",
      leaderboard_opt_out: row.leaderboard_opt_out === 1,
      // Drives whether the UI offers the admin link at all (#116). The
      // endpoints re-check independently -- this flag is convenience, never
      // the authorization.
      is_admin: isAdminId(c.env, row.id),
    },
    linkedin_available: available,
  });
});

/** Where the callback may send a just-signed-in player (#277). Same-origin
 * app paths only: one leading slash, so "//evil.example" and absolute URLs
 * are rejected. Anything else falls back to the historical /play. */
function safeReturnPath(raw: string | undefined): string | null {
  return raw && /^\/(?!\/)/.test(raw) ? raw : null;
}

auth.get("/api/auth/linkedin", (c) => {
  if (!linkedinConfigured(c.env))
    return c.json({ error: "LinkedIn sign-in not configured", code: "AUTH_UNCONFIGURED" }, 503);
  const state = crypto.randomUUID();
  setCookie(c, STATE_COOKIE, state, {
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
    path: "/api/auth",
    maxAge: 600,
  });
  // Carry the page that sent the player here through the OAuth round trip
  // (#277), so sign-in returns them to what they were doing rather than to
  // a hardcoded landing. Validated on write AND on read: a cookie is
  // client-controlled state.
  const returnTo = safeReturnPath(c.req.query("return"));
  if (returnTo)
    setCookie(c, RETURN_COOKIE, returnTo, {
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
      path: "/api/auth",
      maxAge: 600,
    });
  const q = new URLSearchParams({
    response_type: "code",
    client_id: c.env.LINKEDIN_CLIENT_ID,
    redirect_uri: callbackUrl(c.req.url),
    scope: "openid profile email",
    state,
  });
  return c.redirect(`${AUTHORIZE_URL}?${q.toString()}`);
});

auth.get("/api/auth/callback", async (c) => {
  if (!linkedinConfigured(c.env))
    return c.json({ error: "LinkedIn sign-in not configured", code: "AUTH_UNCONFIGURED" }, 503);

  // Provider-declined redirects carry ?error=...; report THAT, never a
  // misleading state-mismatch (#51 — seen live with invalid_scope_error).
  const providerError = c.req.query("error");
  if (providerError) {
    const detail = c.req.query("error_description") ?? "no description";
    console.error(JSON.stringify({ level: "error", message: "linkedin declined", providerError, detail }));
    return c.json(
      { error: `LinkedIn declined the sign-in: ${detail}`, code: "AUTH_PROVIDER", provider_error: providerError },
      400,
    );
  }

  const state = c.req.query("state");
  const code = c.req.query("code");
  const expected = getCookie(c, STATE_COOKIE);
  deleteCookie(c, STATE_COOKIE, { path: "/api/auth" });
  if (!code || !state || !expected || state !== expected)
    return c.json({ error: "OAuth state mismatch", code: "AUTH_STATE" }, 400);

  const tokenRes = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      client_id: c.env.LINKEDIN_CLIENT_ID,
      client_secret: c.env.LINKEDIN_CLIENT_SECRET,
      redirect_uri: callbackUrl(c.req.url),
    }),
  });
  if (!tokenRes.ok) {
    console.error(
      JSON.stringify({ level: "error", message: "linkedin token exchange failed", status: tokenRes.status }),
    );
    return c.json({ error: "Token exchange failed", code: "AUTH_EXCHANGE" }, 502);
  }
  const { access_token } = await tokenRes.json<{ access_token?: string }>();
  if (!access_token) return c.json({ error: "No access token", code: "AUTH_EXCHANGE" }, 502);

  const infoRes = await fetch(USERINFO_URL, {
    headers: { Authorization: `Bearer ${access_token}` },
  });
  // access_token is deliberately dropped after this call — never persisted.
  if (!infoRes.ok)
    return c.json({ error: "userinfo failed", code: "AUTH_USERINFO" }, 502);
  // `picture` arrives whether we want it or not — the OIDC `profile` scope
  // includes it — and is deliberately not destructured, not stored, and not
  // logged (#190). The claim we make is that we discard it, not that we are
  // never sent it; the second would be false.
  const info = await infoRes.json<{
    sub?: string;
    name?: string;
    email?: string;
    email_verified?: boolean;
  }>();
  if (!info.sub) return c.json({ error: "No subject claim", code: "AUTH_USERINFO" }, 502);

  const playerId = `linkedin:${info.sub}`;
  const now = new Date().toISOString();
  // LinkedIn asserting `email_verified` is a verification we do not need to
  // repeat (#104) — seed the notification address already-verified. An
  // unverified claim is still stored as identity but earns no send rights.
  const seedNotify = info.email && info.email_verified === true ? info.email : null;
  // Asked BEFORE the upsert: afterwards every sign-in looks identical, and
  // the operator alert (#100) is specifically about the first one.
  const existing = await c.env.DB.prepare("SELECT 1 FROM players WHERE id = ?")
    .bind(playerId)
    .first<{ 1: number }>();
  await c.env.DB.prepare(
    `INSERT INTO players (id, kind, display_name, email, created_at, last_seen_at,
                          notify_email, notify_email_verified_at)
     VALUES (?, 'human', ?, ?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET
       display_name = excluded.display_name,
       -- A player who removed their address (#192) must not have the provider
       -- write it back on the next sign-in. The marker is the whole point of
       -- the feature: without this CASE the choice survives until they log in
       -- again, which is no choice at all.
       email = CASE WHEN players.email_declined_at IS NOT NULL
                    THEN NULL ELSE excluded.email END,
       last_seen_at = excluded.last_seen_at,
       -- COALESCE, never excluded: a player who chose their own address must
       -- not have it silently reset to the LinkedIn one on every sign-in.
       notify_email = CASE WHEN players.email_declined_at IS NOT NULL
                           THEN NULL
                           ELSE COALESCE(players.notify_email, excluded.notify_email) END,
       notify_email_verified_at =
         CASE WHEN players.email_declined_at IS NOT NULL
              THEN NULL
              ELSE COALESCE(players.notify_email_verified_at,
                            excluded.notify_email_verified_at) END`,
  )
    .bind(
      playerId,
      info.name ?? null,
      info.email ?? null,
      now,
      now,
      seedNotify,
      seedNotify ? now : null,
    )
    .run();

  if (!existing)
    notifyOperator(c.env, c.executionCtx, newPlayerMail(info.name ?? null, playerId));

  // Audit the sign-in (#116). Best-effort: recordLogin swallows its own
  // errors, so a failed audit row never costs a player their sign-in.
  c.executionCtx.waitUntil(recordLogin(c.env, playerId));

  setCookie(c, SESSION_COOKIE, await signSession(playerId, c.env.SESSION_SECRET), {
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  // Return the player to the page that sent them into the OAuth flow (#277);
  // /play remains the default for entries that carried no return.
  const returnTo = safeReturnPath(getCookie(c, RETURN_COOKIE));
  deleteCookie(c, RETURN_COOKIE, { path: "/api/auth" });
  return c.redirect(returnTo ?? "/play");
});

auth.post("/api/auth/logout", (c) => {
  deleteCookie(c, SESSION_COOKIE, { path: "/" });
  return c.json({ ok: true });
});
