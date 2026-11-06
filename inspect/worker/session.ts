// GENERATED from martymcenroe/Palaestra by tools/export_exedra.py (#323). Do not edit it here: a change made here is overwritten by the next export and fails the drift test. Change it upstream, or open an issue with a scenario pack that shows the problem.

/**
 * Session plumbing (M2: anonymous guests; M4 adds LinkedIn OIDC on top).
 *
 * The session cookie carries `v2.<issuedAt>.<epoch>.<playerId>.<hmac>`: an
 * HMAC-SHA256 signature with SESSION_SECRET over a purpose string and
 * everything before it, so nobody can forge another player's id, move the
 * issue time or change the epoch by editing the cookie. Provider tokens are
 * never stored anywhere (0013 §2.7).
 *
 * The cookie is no longer the whole session (#682). The Worker refuses a token
 * older than SESSION_LIFETIME_S, so the 30 days hold even when a browser keeps
 * the cookie longer. It also refuses one whose epoch differs from the
 * player's row, so raising the row's epoch ends every session the player
 * holds, on every device. Signing out raises it. A token from before this
 * format (`<playerId>.<hmac>`) never verifies, so it reads as signed out.
 */

import type { Context } from "hono";
import { getCookie } from "hono/cookie";

export const SESSION_COOKIE = "palaestra_session";

/** A session's lifetime, checked by the Worker as well as by the cookie's
 * Max-Age in the browser (#682). */
export const SESSION_LIFETIME_S = 60 * 60 * 24 * 30;

/** How far ahead of the Worker's clock an issue time may be and still be
 * accepted: tokens are minted by this same Worker, so only clock skew
 * between locations explains a later one. */
const FUTURE_SKEW_S = 300;

/** The token format's marker, and the purpose string under the MAC that keeps
 * this signature apart from every other HMAC the Worker makes (the
 * unsubscribe token's among them) and from the old session format. */
const VERSION = "v2";
const PURPOSE = "palaestra-session-v2";

/** The one read a session costs: the row's epoch and when the row was made.
 * Exported so a test's D1 stand-in can answer it by name. */
export const SESSION_LOOKUP_SQL = "SELECT session_epoch, created_at FROM players WHERE id = ?";

const encoder = new TextEncoder();

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

function b64url(bytes: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function mac(payload: string, secret: string): Promise<string> {
  const key = await hmacKey(secret);
  return b64url(await crypto.subtle.sign("HMAC", key, encoder.encode(`${PURPOSE}\n${payload}`)));
}

/** What a verified token claims. The epoch still has to match the player's
 * row before the claim names a signed-in player (`sessionPlayer`). */
export interface SessionClaims {
  playerId: string;
  epoch: number;
  /** Seconds since the epoch, when the token was minted. */
  issuedAt: number;
}

/** Mint a session for `playerId` at the epoch its row holds now. */
export async function signSession(
  playerId: string,
  epoch: number,
  secret: string,
  nowMs: number = Date.now(),
): Promise<string> {
  if (!Number.isSafeInteger(epoch) || epoch < 0) throw new Error(`session epoch must be a non-negative integer, got ${epoch}`);
  const payload = `${VERSION}.${Math.floor(nowMs / 1000)}.${epoch}.${playerId}`;
  return `${payload}.${await mac(payload, secret)}`;
}

/** Equal-length byte comparison that reads every byte whatever it finds, so
 * the time taken says nothing about where two tokens first differ. */
function sameBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.byteLength !== b.byteLength) return false;
  let diff = 0;
  // i < byteLength bounds both reads; assertions are type-only (#243).
  for (let i = 0; i < a.byteLength; i++) diff |= a[i]! ^ b[i]!;
  return diff === 0;
}

/** The token's claims if its MAC holds and it is inside its lifetime, else
 * null. Pure: it checks no row, so a revoked token can still verify here. */
export async function verifySession(
  token: string,
  secret: string,
  nowMs: number = Date.now(),
): Promise<SessionClaims | null> {
  const at = token.lastIndexOf(".");
  if (at <= 0) return null;
  const payload = token.slice(0, at);
  // timing-safe: the whole expected token against the whole given one, over
  // fixed-length digests, before anything in the payload is trusted.
  if (!sameBytes(encoder.encode(`${payload}.${await mac(payload, secret)}`), encoder.encode(token))) return null;
  const m = /^v2\.(\d{1,12})\.(\d{1,9})\.(.+)$/s.exec(payload);
  if (!m) return null;
  const issuedAt = Number(m[1]);
  const epoch = Number(m[2]);
  const playerId = m[3]!;
  const now = Math.floor(nowMs / 1000);
  if (issuedAt > now + FUTURE_SKEW_S) return null;
  if (now - issuedAt >= SESSION_LIFETIME_S) return null;
  return { playerId, epoch, issuedAt };
}

/**
 * The signed-in player a token names, or null.
 *
 * Three things beyond the MAC and the lifetime: the player's row exists (an
 * erased player has none); its epoch is the token's (signing out raises it);
 * and the row is no newer than the token. The last check matters after an
 * erasure: a person who signs in again gets a new row at epoch 0, and a token
 * copied before the erasure would otherwise match it.
 */
export async function sessionPlayer(
  DB: Env["DB"],
  token: string,
  secret: string,
  nowMs: number = Date.now(),
): Promise<string | null> {
  const claims = await verifySession(token, secret, nowMs);
  if (!claims) return null;
  const row = await DB.prepare(SESSION_LOOKUP_SQL)
    .bind(claims.playerId)
    .first<{ session_epoch: number; created_at: string }>();
  if (!row) return null;
  if (Number(row.session_epoch) !== claims.epoch) return null;
  const created = Date.parse(row.created_at);
  if (!Number.isFinite(created) || Math.floor(created / 1000) > claims.issuedAt) return null;
  return claims.playerId;
}

/** End every session the player holds, on every device (#682). */
export async function endSessions(DB: Env["DB"], playerId: string): Promise<void> {
  await DB.prepare("UPDATE players SET session_epoch = session_epoch + 1 WHERE id = ?")
    .bind(playerId)
    .run();
}

/** The epoch a new session for this player is minted at: the row's, read
 * after the sign-in's upsert. A missing row there is a failure, never a
 * default. */
export async function currentEpoch(DB: Env["DB"], playerId: string): Promise<number> {
  const row = await DB.prepare("SELECT session_epoch FROM players WHERE id = ?")
    .bind(playerId)
    .first<{ session_epoch: number }>();
  const epoch = Number(row?.session_epoch);
  if (!row || !Number.isSafeInteger(epoch) || epoch < 0)
    throw new Error(`no session epoch for ${playerId} after its sign-in's upsert`);
  return epoch;
}

/** Verify-only: the current player id, or null. Never creates a guest —
 * use for endpoints that must not mint players as a side effect. */
export async function currentPlayer(c: Context<{ Bindings: Env }>): Promise<string | null> {
  const token = getCookie(c, SESSION_COOKIE);
  if (!token) return null;
  return sessionPlayer(c.env.DB, token, c.env.SESSION_SECRET);
}

/**
 * The current player id, or null when nobody is signed in.
 *
 * Guest play is DISABLED (operator directive, 2026-07-27). This function
 * replaced `ensurePlayer`, which minted `guest:<uuid>` rows on first contact —
 * the rename is deliberate: a function named "ensure" invites callers to treat
 * its result as always present, which is exactly how anonymous play would
 * creep back in. Every caller must now handle null and refuse the request.
 *
 * Play requires an identity. Uses the wrangler-generated global Env (never a
 * hand-written twin — they drift).
 */
export async function requirePlayer(
  c: Context<{ Bindings: Env }>,
): Promise<string | null> {
  const token = getCookie(c, SESSION_COOKIE);
  if (!token) return null;
  const playerId = await sessionPlayer(c.env.DB, token, c.env.SESSION_SECRET);
  if (!playerId) return null;
  await c.env.DB.prepare("UPDATE players SET last_seen_at = ? WHERE id = ?")
    .bind(new Date().toISOString(), playerId)
    .run();
  return playerId;
}
