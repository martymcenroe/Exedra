// GENERATED from martymcenroe/Palaestra by tools/export_exedra.py (#323). Do not edit it here: a change made here is overwritten by the next export and fails the drift test. Change it upstream, or open an issue with a scenario pack that shows the problem.

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
 *
 * GitHub is the second provider (#636), added for the UNT session, where a
 * student without a LinkedIn account could not otherwise play. It is OAuth,
 * not OIDC: `GET /user` gives the stable numeric id (`github:<id>`; the login
 * can be renamed), and `GET /user/emails` gives the primary verified address.
 * The only scope asked for is `user:email`; `/user` needs none for the public
 * profile, and `read:user` would add private fields Palaestra has no use for.
 * Both providers share the state and return cookies and the one player
 * upsert, so the guards on a player's own choices (#192, #427) cannot drift
 * apart between them.
 */

import { Hono, type Context } from "hono";
import { deleteCookie, getCookie, setCookie } from "hono/cookie";

import { safeReturnPath } from "../shared/return-path";
import { isAdminId, recordLogin } from "./admin";
import { newPlayerMail, notifyOperator } from "./notify";
import { providerOf } from "./provider";
import { SESSION_COOKIE, SESSION_LIFETIME_S, currentEpoch, endSessions, sessionPlayer, signSession } from "./session";

const AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization";
const TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken";
const USERINFO_URL = "https://api.linkedin.com/v2/userinfo";
const GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize";
const GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token";
const GITHUB_USER_URL = "https://api.github.com/user";
const GITHUB_EMAILS_URL = "https://api.github.com/user/emails";
/** The whole scope. `GET /user` answers the public profile with no scope. */
export const GITHUB_SCOPE = "user:email";
/** GitHub's REST API rejects a request that carries no User-Agent. */
const GITHUB_API_HEADERS = { Accept: "application/vnd.github+json", "User-Agent": "Palaestra" };
const STATE_COOKIE = "palaestra_oauth_state";
const RETURN_COOKIE = "palaestra_oauth_return";

export const auth = new Hono<{ Bindings: Env }>();

type AuthContext = Context<{ Bindings: Env }>;

function linkedinConfigured(env: Env): boolean {
  return Boolean(env.LINKEDIN_CLIENT_ID && env.LINKEDIN_CLIENT_SECRET);
}

/** What GitHub sign-in reads beyond the generated Env. Optional in the type
 * because absence is a real state until the operator registers the app and
 * types its secret (#636, runbook 0004), and it is refused by name. */
type GitHubEnv = Env & { GITHUB_CLIENT_ID?: string; GITHUB_CLIENT_SECRET?: string };

function githubSettings(env: Env): { id: string; secret: string } | null {
  const { GITHUB_CLIENT_ID: id, GITHUB_CLIENT_SECRET: secret } = env as GitHubEnv;
  return id && secret ? { id, secret } : null;
}

function githubConfigured(env: Env): boolean {
  return githubSettings(env) !== null;
}

function callbackUrl(reqUrl: string): string {
  const u = new URL(reqUrl);
  return `${u.origin}/api/auth/callback`;
}

function githubCallbackUrl(reqUrl: string): string {
  const u = new URL(reqUrl);
  return `${u.origin}/api/auth/github/callback`;
}

/** Which providers can mint a session right now. The client shows a button
 * only for a provider that is true here. */
function availability(env: Env) {
  return { linkedin_available: linkedinConfigured(env), github_available: githubConfigured(env) };
}

auth.get("/api/auth/me", async (c) => {
  const available = availability(c.env);
  const token = getCookie(c, SESSION_COOKIE);
  if (!token) return c.json({ player: null, ...available });
  const playerId = await sessionPlayer(c.env.DB, token, c.env.SESSION_SECRET);
  if (!playerId) return c.json({ player: null, ...available });
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
  if (!row) return c.json({ player: null, ...available });
  return c.json({
    player: {
      id: row.id,
      display_name: row.display_name,
      provider: providerOf(row.id),
      leaderboard_opt_out: row.leaderboard_opt_out === 1,
      // Drives whether the UI offers the admin link at all (#116). The
      // endpoints re-check independently -- this flag is convenience, never
      // the authorization.
      is_admin: isAdminId(c.env, row.id),
    },
    ...available,
  });
});

/** Where the callback may send a just-signed-in player (#277, #681): a path on
 * the request's own origin, by `shared/return-path.ts`. Anything else falls
 * back to the historical /play. */
function returnPathFor(c: AuthContext, raw: string | undefined): string | null {
  return safeReturnPath(raw, new URL(c.req.url).origin);
}

/** Set the state cookie that blocks a forged callback, and the return cookie,
 * for either provider's authorize redirect. Returns the state to send. */
function beginOAuth(c: AuthContext): string {
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
  const returnTo = returnPathFor(c, c.req.query("return"));
  if (returnTo)
    setCookie(c, RETURN_COOKIE, returnTo, {
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
      path: "/api/auth",
      maxAge: 600,
    });
  return state;
}

auth.get("/api/auth/linkedin", (c) => {
  if (!linkedinConfigured(c.env))
    return c.json({ error: "LinkedIn sign-in not configured", code: "AUTH_UNCONFIGURED" }, 503);
  const state = beginOAuth(c);
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

  const code = verifiedCode(c);
  if (!code) return c.json({ error: "OAuth state mismatch", code: "AUTH_STATE" }, 400);

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

  // LinkedIn asserting `email_verified` is a verification we do not need to
  // repeat (#104) — seed the notification address already-verified. An
  // unverified claim is still stored as identity but earns no send rights.
  return completeSignIn(c, {
    playerId: `linkedin:${info.sub}`,
    name: info.name ?? null,
    email: info.email ?? null,
    verifiedEmail: info.email && info.email_verified === true ? info.email : null,
    providerName: "LinkedIn",
  });
});

/** The callback's forged-request check, shared by both providers. The state
 * cookie is consumed either way. Returns the code only when the state the
 * provider echoed matches the cookie. */
function verifiedCode(c: AuthContext): string | null {
  const state = c.req.query("state");
  const code = c.req.query("code");
  const expected = getCookie(c, STATE_COOKIE);
  deleteCookie(c, STATE_COOKIE, { path: "/api/auth" });
  return code && state && expected && state === expected ? code : null;
}

/** Who a provider says signed in, in the terms the player record keeps. */
interface Identity {
  /** Provider-prefixed (0013 §2.5): `linkedin:<sub>` or `github:<id>`. */
  playerId: string;
  name: string | null;
  /** The address the provider sends, kept as identity. */
  email: string | null;
  /** An address the provider asserts is verified, seeded as the notification
   * address (#104). Null when the provider asserts none. */
  verifiedEmail: string | null;
  /** For the operator's first-sign-in alert (#100). */
  providerName: "LinkedIn" | "GitHub";
}

/** Upsert the player, alert on a first sign-in, audit it, mint the session and
 * send the player back where they came from. One path for every provider. */
async function completeSignIn(c: AuthContext, who: Identity): Promise<Response> {
  const { playerId } = who;
  const now = new Date().toISOString();
  const seedNotify = who.verifiedEmail;
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
       -- A player who chose their own board name (#427) must not have the
       -- provider write it back on the next sign-in. Same reasoning as the
       -- declined address below: a choice a later sign-in reverses is no
       -- choice at all. Unset for everyone who has not chosen, so the
       -- provider's name keeps arriving by default.
       display_name = CASE WHEN players.display_name_chosen_at IS NOT NULL
                           THEN players.display_name ELSE excluded.display_name END,
       -- A player who removed their address (#192) must not have the provider
       -- write it back on the next sign-in. The marker is the whole point of
       -- the feature: without this CASE the choice survives until they log in
       -- again, which is no choice at all.
       email = CASE WHEN players.email_declined_at IS NOT NULL
                    THEN NULL ELSE excluded.email END,
       last_seen_at = excluded.last_seen_at,
       -- COALESCE, never excluded: a player who chose their own address must
       -- not have it silently reset to the provider's one on every sign-in.
       notify_email = CASE WHEN players.email_declined_at IS NOT NULL
                           THEN NULL
                           ELSE COALESCE(players.notify_email, excluded.notify_email) END,
       notify_email_verified_at =
         CASE WHEN players.email_declined_at IS NOT NULL
              THEN NULL
              ELSE COALESCE(players.notify_email_verified_at,
                            excluded.notify_email_verified_at) END`,
  )
    .bind(playerId, who.name, who.email, now, now, seedNotify, seedNotify ? now : null)
    .run();

  if (!existing)
    notifyOperator(c.env, c.executionCtx, newPlayerMail(who.name, playerId, who.providerName));

  // Audit the sign-in (#116). Best-effort: recordLogin swallows its own
  // errors, so a failed audit row never costs a player their sign-in.
  c.executionCtx.waitUntil(recordLogin(c.env, playerId));

  // Minted at the epoch the row holds now (#682): a sign-out on any device
  // raised it, and this session is the first at the new one.
  const epoch = await currentEpoch(c.env.DB, playerId);
  setCookie(c, SESSION_COOKIE, await signSession(playerId, epoch, c.env.SESSION_SECRET), {
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
    path: "/",
    maxAge: SESSION_LIFETIME_S,
  });
  // Return the player to the page that sent them into the OAuth flow (#277);
  // /play remains the default for entries that carried no return.
  const returnTo = returnPathFor(c, getCookie(c, RETURN_COOKIE));
  deleteCookie(c, RETURN_COOKIE, { path: "/api/auth" });
  return c.redirect(returnTo ?? "/play");
}

/** GitHub unconfigured (#636 R7): a named refusal, logged, and LinkedIn is
 * untouched. Expected before the operator types the client secret; after
 * that, this line in the log means a setting went missing. */
function githubUnconfigured(c: AuthContext, route: "start" | "callback"): Response {
  console.error(JSON.stringify({ level: "error", message: "github sign-in not configured", route }));
  return c.json({ error: "GitHub sign-in not configured", code: "AUTH_UNCONFIGURED" }, 503);
}

auth.get("/api/auth/github", (c) => {
  const gh = githubSettings(c.env);
  if (!gh) return githubUnconfigured(c, "start");
  const state = beginOAuth(c);
  // `allow_signup` is left at GitHub's default, true: a student with no
  // GitHub account can make one inside the flow.
  const q = new URLSearchParams({
    client_id: gh.id,
    redirect_uri: githubCallbackUrl(c.req.url),
    scope: GITHUB_SCOPE,
    state,
  });
  return c.redirect(`${GITHUB_AUTHORIZE_URL}?${q.toString()}`);
});

auth.get("/api/auth/github/callback", async (c) => {
  const gh = githubSettings(c.env);
  if (!gh) return githubUnconfigured(c, "callback");

  // A cancelled or refused authorization arrives as ?error=access_denied.
  // Report that, never a misleading state mismatch (#51).
  const providerError = c.req.query("error");
  if (providerError) {
    const detail = c.req.query("error_description") ?? "no description";
    console.error(JSON.stringify({ level: "error", message: "github declined", providerError, detail }));
    return c.json(
      { error: `GitHub declined the sign-in: ${detail}`, code: "AUTH_PROVIDER", provider_error: providerError },
      400,
    );
  }

  const code = verifiedCode(c);
  if (!code) return c.json({ error: "OAuth state mismatch", code: "AUTH_STATE" }, 400);

  const tokenRes = await fetch(GITHUB_TOKEN_URL, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded",
      "User-Agent": "Palaestra",
    },
    body: new URLSearchParams({
      client_id: gh.id,
      client_secret: gh.secret,
      code,
      redirect_uri: githubCallbackUrl(c.req.url),
    }),
  });
  // GitHub answers a refused exchange with 200 and an `error` field, so the
  // status proves nothing: the token's presence is the test.
  const token = tokenRes.ok ? await tokenRes.json<{ access_token?: string; error?: string }>() : null;
  if (!token?.access_token) {
    console.error(
      JSON.stringify({
        level: "error",
        message: "github token exchange failed",
        status: tokenRes.status,
        provider_error: token?.error ?? null,
      }),
    );
    return c.json({ error: "Token exchange failed", code: "AUTH_EXCHANGE" }, 502);
  }

  const headers = { ...GITHUB_API_HEADERS, Authorization: `Bearer ${token.access_token}` };
  const [userRes, emailsRes] = await Promise.all([
    fetch(GITHUB_USER_URL, { headers }),
    fetch(GITHUB_EMAILS_URL, { headers }),
  ]);
  // The access token is dropped after these two calls — never persisted.
  if (!userRes.ok || !emailsRes.ok) {
    console.error(
      JSON.stringify({
        level: "error",
        message: "github profile read failed",
        user_status: userRes.status,
        emails_status: emailsRes.status,
      }),
    );
    return c.json({ error: "userinfo failed", code: "AUTH_USERINFO" }, 502);
  }
  // The rest of the public profile, `avatar_url` with it, arrives whether we
  // want it or not and is not destructured, stored or logged, as LinkedIn's
  // photo is not (#190).
  const user = await userRes.json<{ id?: number; login?: string; name?: string | null }>();
  if (typeof user.id !== "number")
    return c.json({ error: "No user id", code: "AUTH_USERINFO" }, 502);
  const emails = await emailsRes.json<{ email?: string; primary?: boolean; verified?: boolean }[]>();
  // The primary address GitHub marks verified is a verification we need not
  // repeat (#104), so it is seeded as the notification address. With none,
  // the player has no address at all (#636 R5): an unverified one is never
  // kept, because GitHub lets anyone list any address.
  const primary =
    (Array.isArray(emails) ? emails.find((e) => e.primary === true && e.verified === true) : undefined)
      ?.email ?? null;

  return completeSignIn(c, {
    // The numeric id, never the login: a login can be renamed and then
    // claimed by someone else.
    playerId: `github:${user.id}`,
    name: user.name || user.login || null,
    email: primary,
    verifiedEmail: primary,
    providerName: "GitHub",
  });
});

/** Signing out ends the session on every device (#682): it raises the
 * player's epoch, so every token they hold is refused from then on. Only a
 * session that still verifies raises it, so a copied token that is already
 * dead cannot sign its owner out again and again. A caller whose session has
 * lapsed is still signed out here: the cookie goes either way. */
auth.post("/api/auth/logout", async (c) => {
  const token = getCookie(c, SESSION_COOKIE);
  const playerId = token ? await sessionPlayer(c.env.DB, token, c.env.SESSION_SECRET) : null;
  if (playerId) await endSessions(c.env.DB, playerId);
  deleteCookie(c, SESSION_COOKIE, { path: "/" });
  return c.json({ ok: true });
});
