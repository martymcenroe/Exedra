// GENERATED from martymcenroe/Palaestra by tools/export_exedra.py (#323). Do not edit it here: a change made here is overwritten by the next export and fails the drift test. Change it upstream, or open an issue with a scenario pack that shows the problem.

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
      <p className="mt-1 text-sm text-ink-dim">Effective 2026-11-05 · Palaestra (palaestra.thrivetech.ai)</p>

      <div className="mt-6 space-y-6 text-sm leading-relaxed text-ink-mute">
        <section>
          <h2 className="text-base font-semibold text-ink">Who we are</h2>
          <p className="mt-1">
            Thrive Tech owns Palaestra and is the controller of its data.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-ink">What we collect</h2>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            <li>
              You sign in with LinkedIn or GitHub. Your player record holds the name and email
              address your sign-in provider sends us, with the identifier the provider keeps for
              you. A GitHub name is your username when your profile sets no name, and a GitHub
              address is your primary verified address. Your sign-in records hold the time of
              each sign-in. We also receive a profile photo URL from LinkedIn and discard it within
              the sign-in request. We receive your public profile and your list of email addresses
              from GitHub, and we discard the rest of both within the sign-in request.
            </li>
            <li>
              Your episode data holds the scenario state and your committed action on each turn,
              with each episode's score. Guest accounts hold only a random identifier and episode
              data.
            </li>
            <li>
              We keep an onboarding record of each of these events, with its time:
              <ul className="mt-1 list-[circle] space-y-1 pl-5">
                <li>reaching a step of the guided tour</li>
                <li>committing your first turn</li>
                <li>pausing for 10 seconds</li>
                <li>starting the scenario suggested at the end of an episode</li>
              </ul>
              We read the onboarding records and the last turn of each unfinished episode to
              find the points where new players pause or quit the game.
            </li>
            <li>
              We keep concept inferences, which estimate the concepts you have learned from your
              play and your work in the lessons. We use the inferences to choose your lesson
              questions and the scenarios available to you.
            </li>
            <li>
              A problem report you send carries these items:
              <ul className="mt-1 list-[circle] space-y-1 pl-5">
                <li>your message</li>
                <li>the page you were on, without its query parameter values</li>
                <li>the app version</li>
                <li>your player identity, since only a signed-in player can send a report</li>
              </ul>
              If you keep the technical trace attached, the report also carries the trace your
              browser holds in memory:
              <ul className="mt-1 list-[circle] space-y-1 pl-5">
                <li>recent in-app errors, with their request references</li>
                <li>
                  the results of any connection check you ran, which say only whether a session
                  was present
                </li>
                <li>your browser's user-agent string</li>
              </ul>
              The browser removes any value in the form of a credential, such as a token or an
              authorization code, before the value enters the trace. The trace leaves your
              machine only when you send a problem report. We use problem reports only to fix
              the reported problems.
            </li>
            <li>
              If you enter a notification address on your profile, or accept the one your
              sign-in provider supplies, we use it only for your chosen notifications. You can remove it from
              your profile at any time. We keep a record of each notification we prepare for
              you.
            </li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold text-ink">Sign-in and cookies</h2>
          <p className="mt-1">
            We use your sign-in provider's access token only within the sign-in request, to read
            your profile and email address, and then discard it. Palaestra sets cookies only for
            sign-in, and they hold these values:
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            <li>your session, which lasts 30 days unless you sign out sooner</li>
            <li>a random value that blocks forged sign-ins, for 10 minutes</li>
            <li>the page you came from, if any, for 10 minutes</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold text-ink">Leaderboards</h2>
          <p className="mt-1">
            Public leaderboards may show your display name and scores. You can opt out and keep
            your account. An opt-out hides your entries from public view.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-ink">Research</h2>
          <p className="mt-1">
            We may analyze episode data and publish the results as research on gaps in
            technical standards. We publish only aggregated or de-identified analysis, and we
            attach your name to a published result only with your explicit consent.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-ink">Storage and your rights</h2>
          <p className="mt-1">
            Cloudflare stores the data for us. We never sell or rent personal data. We keep the
            records keyed to your identity until you ask for erasure.
          </p>
          <p className="mt-1">
            To erase those records, email{" "}
            <a
              href="mailto:GDPR-request@palaestra.thrivetech.ai"
              className="text-accent hover:underline"
            >
              GDPR-request@palaestra.thrivetech.ai
            </a>
            . We delete these records within 30 days of your request, for anyone in any country:
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            <li>your player record</li>
            <li>your episode data</li>
            <li>your sign-in records</li>
            <li>your problem reports and their traces</li>
            <li>your onboarding records</li>
            <li>your concept inferences</li>
            <li>your notification records</li>
          </ul>
          <p className="mt-1">
            Write to{" "}
            <a
              href="mailto:GDPR-request@palaestra.thrivetech.ai"
              className="text-accent hover:underline"
            >
              GDPR-request@palaestra.thrivetech.ai
            </a>{" "}
            for a copy of any record in this list. We send each copy within 30 days. The download on your profile carries your player
            record and sign-in records, with your episode data. For any other privacy question,
            write to{" "}
            <a href="mailto:support@palaestra.thrivetech.ai" className="text-accent hover:underline">
              support@palaestra.thrivetech.ai
            </a>
            .
          </p>
        </section>
      </div>
    </div>
  );
}
