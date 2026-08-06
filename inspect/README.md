# inspect/

Verbatim copies of code running at
[palaestra.thrivetech.ai](https://palaestra.thrivetech.ai), published so the
claims made about it can be checked rather than taken on trust.

**This is not a buildable application.** It is a reading copy. The rest of this
repository is the contributor toolkit; this directory exists for anyone
evaluating whether the service is safe to allow, integrate with, or sign in to.

Start with [SECURITY.md](../SECURITY.md), which answers the usual questions in
about ninety seconds and points back here for the evidence.

## What is here

| File | What it lets you confirm |
|---|---|
| `worker/auth.ts` | The whole sign-in flow. One identity provider, which endpoints are called, what is requested, what is stored, and the session cookie's attributes. |
| `worker/session.ts` | The session cookie is an HMAC over a player id, verified locally. It is not a token exchanged with anyone. |
| `worker/support.ts` | The problem-report endpoint. Limits, what is written, and that a report works without an account. |
| `web/connection-check.tsx` | The self-diagnostic a stuck visitor is sent to. Everything it measures is a property of the visitor's own browser. |
| `web/privacy-policy.tsx` | The published policy, as source, including what is refused. |
| `wrangler.jsonc` | Every binding the service has. Two values redacted, both marked. |

## Two facts worth checking yourself

**The browser contacts no external host.** No content delivery network, no
analytics, no web fonts, no tracker, no error reporting. The only external
strings in the built bundle are the SVG XML namespace and two documentation
URLs inside a markdown library's error messages, and none of them is ever
fetched.

**The server contacts LinkedIn and nothing else.** `www.linkedin.com` and
`api.linkedin.com`, during sign-in only.

Both are visible in a few minutes of reading, which is why they are stated
this plainly.

## How these copies stay honest

They are copied from the platform rather than maintained here, the same way the
engine and the acceptance gate are. Editing a file in this directory changes
nothing about what runs; it only makes the copy wrong. See
[Hydration](https://github.com/martymcenroe/Exedra/wiki/Hydration).

If you find a difference between what is here and what the service does, that
is a report worth making, and the fastest way is a GitHub issue on this
repository.
