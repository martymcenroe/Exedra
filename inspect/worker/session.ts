/**
 * Session plumbing (M2: anonymous guests; M4 adds LinkedIn OIDC on top).
 *
 * The session cookie carries `<playerId>.<hmac>` — an HMAC-SHA256 signature
 * over the player id with SESSION_SECRET, so a guest cannot forge someone
 * else's id by editing the cookie. Provider tokens are never stored
 * anywhere (0013 §2.7); the cookie is the whole session.
 */

import type { Context } from "hono";
import { getCookie } from "hono/cookie";

export const SESSION_COOKIE = "palaestra_session";

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

export async function signSession(playerId: string, secret: string): Promise<string> {
  const key = await hmacKey(secret);
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(playerId));
  return `${playerId}.${b64url(sig)}`;
}

export async function verifySession(token: string, secret: string): Promise<string | null> {
  const at = token.lastIndexOf(".");
  if (at <= 0) return null;
  const playerId = token.slice(0, at);
  const expected = await signSession(playerId, secret);
  // timing-safe: compare fixed-length digests, not the variable-length token
  const a = encoder.encode(expected);
  const b = encoder.encode(token);
  if (a.byteLength !== b.byteLength) return null;
  let diff = 0;
  // i < byteLength bounds both reads; assertions are type-only (#243).
  for (let i = 0; i < a.byteLength; i++) diff |= a[i]! ^ b[i]!;
  return diff === 0 ? playerId : null;
}

/** Verify-only: the current player id, or null. Never creates a guest —
 * use for endpoints that must not mint players as a side effect. */
export async function currentPlayer(c: Context<{ Bindings: Env }>): Promise<string | null> {
  const token = getCookie(c, SESSION_COOKIE);
  if (!token) return null;
  return verifySession(token, c.env.SESSION_SECRET);
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
  const playerId = await verifySession(token, c.env.SESSION_SECRET);
  if (!playerId) return null;
  await c.env.DB.prepare("UPDATE players SET last_seen_at = ? WHERE id = ?")
    .bind(new Date().toISOString(), playerId)
    .run();
  return playerId;
}
