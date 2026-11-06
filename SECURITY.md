# Security

Palaestra is a browser-based teaching simulation at
[palaestra.thrivetech.ai](https://palaestra.thrivetech.ai). It is
noncommercial, sells nothing, and processes no payments.

## Reviewing the service

Two pages, maintained in the wiki:

- **[Security Review](https://github.com/martymcenroe/Exedra/wiki/Security-Review)**:
  hosts contacted, the sign-in flow hop by hop, sessions, authorization,
  secrets, unauthenticated endpoints, logging, supply chain.
- **[Privacy Review](https://github.com/martymcenroe/Exedra/wiki/Privacy-Review)**:
  data held with purpose and retention, what is refused, sub-processors,
  cookies, and how each right is exercised.

Two facts that decide most questions:

- Apart from the sign-in provider's own page during sign-in, the browser
  contacts no host other than `palaestra.thrivetech.ai`. No CDN, analytics, web
  font, advertising network, tracker, or error-reporting service.
- The server contacts these hosts and no others:
  - `www.linkedin.com` and `api.linkedin.com`, during a LinkedIn sign-in;
  - `github.com` and `api.github.com`, during a GitHub sign-in, once GitHub
    sign-in is switched on;
  - `email.us-east-1.amazonaws.com`, AWS's email service, to send mail a
    player asked for, once player mail is switched on.

## If you filter traffic

Sign-in sends the browser to the provider the player chooses, LinkedIn or
GitHub, and **back to this site**: to
`https://palaestra.thrivetech.ai/api/auth/callback` from LinkedIn, or to
`https://palaestra.thrivetech.ai/api/auth/github/callback` from GitHub.
Permitting `palaestra.thrivetech.ai` but blocking either URL fails sign-in after
the user has already authenticated, which the user experiences as the site being
broken.

## Verify

Copies of the running code are in [`inspect/`](inspect/). They cover the
sign-in flow, session signing, the unauthenticated endpoint, the connection
check and the privacy policy source. The deployment binding configuration is
there too, with three values redacted and marked.

## Reporting

Vulnerabilities and security questions: `support@palaestra.thrivetech.ai`.
Erasure requests: `GDPR-request@palaestra.thrivetech.ai`.

There is no bounty programme. Reports are read and answered.
