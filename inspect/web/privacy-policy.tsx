import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/privacy-policy")({
  component: PrivacyPolicy,
});

/** Honest and short (#41): what the venue records, why, and what it never
 * does. Written for a reader, not a compliance scanner. */
function PrivacyPolicy() {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-12">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">Privacy policy</h1>
      <p className="mt-1 text-sm text-ink-dim">Effective 2026-07-26 · Palaestra (palaestra.thrivetech.ai)</p>

      <div className="mt-6 space-y-6 text-sm leading-relaxed text-ink-mute">
        <section>
          <h2 className="text-base font-semibold text-ink">What Palaestra is</h2>
          <p className="mt-1">
            Palaestra is a noncommercial educational venue and research instrument for the
            interface between the electric grid and very large loads. Understanding what it
            collects starts with what it is: every episode you play produces a log of the
            scenario's observations, your actions, and the resolved outcomes. That log is the
            point — it is how the venue discovers where technical rules bend.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-ink">What we collect</h2>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            <li>
              <strong className="text-ink">Sign-in required:</strong> playing requires signing
              in; guest play is closed. Historical guest accounts (a random identifier and
              episode data, nothing identifying) keep their records under the same rights
              described here.
            </li>
            <li>
              <strong className="text-ink">If you sign in with LinkedIn:</strong> your name,
              email address, and LinkedIn's stable subject identifier. We request no other
              LinkedIn data and cannot see your connections, posts, or activity.
            </li>
            <li>
              <strong className="text-ink">Your photo, which we throw away:</strong> LinkedIn
              includes a profile photo URL in the sign-in response whether we ask for it or
              not, because it travels with the standard profile scope. We do not store it, do
              not display it, and do not log it — it is discarded with the rest of the
              response. We would rather tell you precisely what happens than claim we never
              receive it.
            </li>
            <li>
              <strong className="text-ink">Episode data:</strong> the turns you play — scenario
              state shown to you, actions you commit, scores. Attributed to your player
              identity.
            </li>
            <li>
              <strong className="text-ink">Sign-in records:</strong> the time of each sign-in,
              and nothing else about it — no IP address, no location, no device details.
              Kept ninety days, then deleted automatically.
            </li>
            <li>
              <strong className="text-ink">Problem reports, only when you send one:</strong>{" "}
              your message, the page you were on, the app version, and your player identity if
              you are signed in. If you leave the attach box ticked, the report also carries a
              technical trace kept in your browser's memory: recent in-app errors with their
              request reference IDs, the results of any connection check you ran (including
              whether and as whom you were signed in), the page the trace was captured on, and
              your browser's user-agent string — the one device detail a bug report genuinely
              needs. The trace never leaves your machine on its own — you can download and
              read every line of it before sending — and reports exist solely so we can fix
              what you hit.
            </li>
            <li>
              <strong className="text-ink">Notification address:</strong> only if you provide
              one on your profile (or accept the suggestion from your LinkedIn profile), only
              for the notifications you opt into, and removable there at any time.
            </li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold text-ink">What we never do</h2>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            <li>No selling or renting of personal data, to anyone, ever.</li>
            <li>No advertising, no trackers, no analytics beyond our own server logs.</li>
            <li>
              No storage of LinkedIn access tokens — they are used once to read your profile
              at sign-in and immediately discarded.
            </li>
            <li>Only essential cookies: your session, and a short-lived sign-in CSRF guard.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold text-ink">Retention and leaderboards</h2>
          <p className="mt-1">
            Palaestra is a game, and games keep score. Your episodes and scores are{" "}
            <strong className="text-ink">retained indefinitely</strong> so results remain
            comparable over time. Scores and display names may appear on public leaderboards;
            you can opt out of leaderboard display while keeping your account — your data then
            stays out of any public board but is still retained for play history and research.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-ink">How episode data is used</h2>
          <p className="mt-1">
            Episode logs may be analyzed and published as part of standards-needs research —
            for example, "players given this rule consistently exploited this ambiguity." Any
            published analysis is aggregated or de-identified; your name is never attached to
            published results without your explicit consent.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-ink">Where data lives, and your rights</h2>
          <p className="mt-1">
            Data is stored on Cloudflare infrastructure (D1 and R2). To have every record
            associated with your identity wiped, email{" "}
            <a
              href="mailto:GDPR-request@palaestra.thrivetech.ai"
              className="text-accent hover:underline"
            >
              GDPR-request@palaestra.thrivetech.ai
            </a>{" "}
            — erasure requests are honored within 30 days and remove your player record,
            episodes, turns, and sign-in records completely.{" "}
            <strong className="text-ink">
              This right does not depend on where you live.
            </strong>{" "}
            The address says GDPR because that is the law which named the right, not because
            the right is reserved for the people that law happens to cover. Ask, wherever you
            are, and it is honored the same way. You can download everything we hold about you
            at any time from your profile ("Export my data"). For anything else, write{" "}
            <a href="mailto:support@palaestra.thrivetech.ai" className="text-accent hover:underline">
              support@palaestra.thrivetech.ai
            </a>
            . Signing out removes the session cookie immediately.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-ink">Changes</h2>
          <p className="mt-1">
            If this policy changes materially, the effective date above changes with it, and
            the full history is public in the project's version control.
          </p>
        </section>
      </div>
    </div>
  );
}
