# Security and network behaviour

For anyone deciding whether to allow, integrate with, or sign in to
[palaestra.thrivetech.ai](https://palaestra.thrivetech.ai). Every claim below
can be checked against published source, linked at the end.

## What the site is

A browser-based teaching simulation. A player runs a data center against a
simulated electricity grid for a simulated day and receives a score. It is
noncommercial and there is nothing to buy.

## Hosts the software contacts

| Origin | When | Why |
|---|---|---|
| `palaestra.thrivetech.ai` | Throughout | The application and its API. |
| `www.linkedin.com` | Sign-in only | The OAuth consent screen, as a top-level page navigation. |
| `api.linkedin.com` | Sign-in only | Server to server, to exchange the authorization code for the name and email address of the person signing in. |

**Nothing else.** The browser makes network requests to the site's own origin
and to no other host at any point.

There is no content delivery network, no analytics, no web fonts, no
advertising, no tracking pixel, and no error-reporting service. The only
external strings present in the built JavaScript are the SVG XML namespace and
two documentation URLs inside a markdown library's error messages. None of them
is ever fetched.

The sign-in flow returns the browser to
`palaestra.thrivetech.ai/api/auth/callback`. A filter that permits the site but
blocks that path will fail sign-in after the user has already authenticated.

## What executes in the browser

A static single-page application: JavaScript, HTML and CSS, served from the
site's own origin.

No downloads are offered. No plugin, extension, or local agent is required or
suggested. Nothing is uploaded. There is no file sharing, no messaging between
users, and no user-supplied content rendered to other users.

## Sign-in

LinkedIn OpenID Connect, and no other provider. There is no password anywhere
in the system, so none is created, transmitted, stored, or recoverable.

The session is a cookie holding an HMAC signature over an internal player
identifier, verified by the server against a secret the browser never sees. It
is not a bearer token for any third-party service. The cookie is `HttpOnly`,
`Secure`, `SameSite=Lax`, scoped to the site, and expires after thirty days.

## What is collected

Name, email address, and LinkedIn's stable subject identifier. The gameplay a
player produces. The time of each sign-in.

## What is refused

LinkedIn returns a profile photo URL whether it is requested or not. It is
discarded, not stored, not displayed, not logged.

No IP address is stored. No location. No device fingerprint. Sign-in records
keep the time and nothing else, and are deleted automatically after ninety
days.

Nothing is sold, and nothing is shared with advertisers or data brokers.

## Erasure

Any person may have every record associated with them deleted, by email,
honored within thirty days. The right does not depend on where they live or
whether any particular regulation covers them. Everything held about a player
is also downloadable by that player at any time.

## Diagnostics

`/connection-check` reports what is working from the visitor's own browser:
whether the site answers, clock accuracy, whether cookies can be stored,
whether a session exists, and whether the page's code matches the server's.

It measures only properties of that browser. It does not probe, trace, or
describe the network the visitor is on, and it transmits nothing unless the
visitor presses send on a problem report.

## Verify any of this

Copies of the running code are in [`inspect/`](inspect/):

- [`inspect/worker/auth.ts`](inspect/worker/auth.ts) for the sign-in flow
- [`inspect/worker/session.ts`](inspect/worker/session.ts) for the cookie
- [`inspect/web/privacy-policy.tsx`](inspect/web/privacy-policy.tsx) for what is collected
- [`inspect/web/connection-check.tsx`](inspect/web/connection-check.tsx) for the diagnostic
- [`inspect/wrangler.jsonc`](inspect/wrangler.jsonc) for every external resource the server can reach

The published policy is also live at
[palaestra.thrivetech.ai/privacy-policy](https://palaestra.thrivetech.ai/privacy-policy).

## Reporting a problem

Security concerns: `support@palaestra.thrivetech.ai`. Erasure requests:
`GDPR-request@palaestra.thrivetech.ai`.

If something here does not match what the service actually does, that is worth
telling us, and a GitHub issue on this repository is the fastest route.
