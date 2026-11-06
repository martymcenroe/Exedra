# inspect/

Copies of code running at
[palaestra.thrivetech.ai](https://palaestra.thrivetech.ai), published so the
claims made about it can be checked rather than taken on trust. Each code file
is the running file byte for byte, under a one-line header saying it is
generated. `wrangler.jsonc` has its comments written for this copy and three
values redacted; every binding, setting and other value in it is the deployed
file's.

**This is not a buildable application.** It is a reading copy. The rest of this
repository is the contributor toolkit; this directory exists for anyone
evaluating whether the service is safe to allow, integrate with, or sign in to.

Start with [SECURITY.md](../SECURITY.md), which answers the usual questions in
about ninety seconds and points back here for the evidence.

## What is here

| File | What it lets you confirm |
|---|---|
| `worker/auth.ts` | The whole sign-in flow. Both identity providers, LinkedIn and GitHub, which endpoints are called, what is requested, what is stored, and the session cookie's attributes. |
| `worker/session.ts` | The session cookie is an HMAC over a player id, verified locally. It is not a token exchanged with anyone. |
| `worker/support.ts` | The problem-report endpoint. Limits, what is written, and that only a signed-in player can send a report. |
| `web/connection-check.tsx` | The self-diagnostic a stuck visitor is sent to. Everything it measures is a property of the visitor's own browser. |
| `web/privacy-policy.tsx` | The published policy, as source, including what is refused. |
| `wrangler.jsonc` | Every binding the service has. Three values redacted, each marked. |

## Two facts worth checking yourself

**The browser contacts no external host, apart from the sign-in provider's own
page.** No content delivery network, no
analytics, no web fonts, no tracker, no error reporting. The only external
strings in the built bundle are the SVG XML namespace and two documentation
URLs inside a markdown library's error messages, and none of them is ever
fetched.

**The server contacts the sign-in provider and AWS's email service, and
nothing else.**

- `www.linkedin.com` and `api.linkedin.com` during a LinkedIn sign-in.
- `github.com` and `api.github.com` during a GitHub sign-in, once GitHub
  sign-in is switched on.
- `email.us-east-1.amazonaws.com` to send mail a player asked for, once player
  mail is switched on. The mail code is not copied here.

Both are visible in a few minutes of reading, which is why they are stated
this plainly.

## Where these copies come from

The code files are generated from the platform by its export tool, as the
engine is. `GENERATED.json` lists each one, and `tests/test_generated_files.py`
fails on any byte that differs from its export. A copy is as current as the
last export. `wrangler.jsonc` and this page are written for this directory, and
a test in the platform holds every value in `wrangler.jsonc` to the deployed
file except the three redactions. Editing a file in this directory changes
nothing about what runs; it only makes the copy wrong. See
[Hydration](https://github.com/martymcenroe/Exedra/wiki/Hydration).

If you find a difference between what is here and what the service does, that
is a report worth making. The fastest way is a GitHub issue on this repository.
