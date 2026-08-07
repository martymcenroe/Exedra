# Security

Palaestra is a browser-based teaching simulation at
[palaestra.thrivetech.ai](https://palaestra.thrivetech.ai). It is
noncommercial, sells nothing, and processes no payments.

## Reviewing the service

Two pages, maintained in the wiki:

- **[Security Review](https://github.com/martymcenroe/Exedra/wiki/Security-Review)**
  — hosts contacted, the sign-in flow hop by hop, sessions, authorization,
  secrets, unauthenticated endpoints, logging, supply chain.
- **[Privacy Review](https://github.com/martymcenroe/Exedra/wiki/Privacy-Review)**
  — data held with purpose and retention, what is refused, sub-processors,
  cookies, and how each right is exercised.

Two facts that decide most questions:

- The browser contacts no host other than `palaestra.thrivetech.ai`. No CDN,
  analytics, web font, advertising network, tracker, or error-reporting
  service.
- The server contacts `www.linkedin.com` and `api.linkedin.com`, during
  sign-in only, and nothing else.

## If you filter traffic

Sign-in sends the browser to LinkedIn and **back to this site**, at
`https://palaestra.thrivetech.ai/api/auth/callback`. Permitting
`palaestra.thrivetech.ai` but blocking that URL fails sign-in after the user
has already authenticated, which the user experiences as the site being broken.

## Verify

Copies of the running code are in [`inspect/`](inspect/): the sign-in flow,
session signing, the unauthenticated endpoint, the connection check, the
privacy policy source, and the deployment binding configuration with two values
redacted and marked.

## Reporting

Vulnerabilities and security questions: `support@palaestra.thrivetech.ai`.
Erasure requests: `GDPR-request@palaestra.thrivetech.ai`.

There is no bounty programme. Reports are read and answered.
