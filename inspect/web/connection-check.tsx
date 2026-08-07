import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { Page } from "../components/Page";
import { SupportButton } from "../components/SupportButton";
import { recordTrace } from "../lib/trace";
import { ENGINE_VERSION } from "../../shared/engine";

export const Route = createFileRoute("/connection-check")({
  component: ConnectionCheck,
});

/**
 * The one URL support sends anyone (#291): a screen that says, in plain
 * sentences, what is and is not working from THIS browser. A screenshot of
 * this page replaces an hour of guessing — the 2026-08-04 stale-tab
 * incident (#273) is the founding case. Every result also lands in the
 * client trace, so a support report filed afterwards carries it.
 */

interface CheckRow {
  name: string;
  state: "pass" | "fail" | "info";
  detail: string;
}

async function runChecks(): Promise<CheckRow[]> {
  const rows: CheckRow[] = [];

  // 1 + 2: the API, and this bundle's freshness against it.
  const t0 = performance.now();
  try {
    const res = await fetch("/api/health", { credentials: "include" });
    const ms = Math.round(performance.now() - t0);
    const body: { ok?: boolean; engine_version?: string } = await res.json();
    rows.push({
      name: "Reaching Palaestra",
      state: res.ok && body.ok ? "pass" : "fail",
      detail: res.ok
        ? `The server answered in ${ms} ms.`
        : `The server answered with status ${res.status}.`,
    });
    const serverDate = res.headers.get("date");
    if (serverDate) {
      const skew = Math.abs(Date.now() - new Date(serverDate).getTime());
      rows.push({
        name: "Your clock",
        state: skew < 120_000 ? "pass" : "fail",
        detail:
          skew < 120_000
            ? "Within two minutes of the server's."
            : `About ${Math.round(skew / 60_000)} minutes off the server's — sign-in can fail this way.`,
      });
    }
    rows.push(
      body.engine_version === ENGINE_VERSION
        ? {
            name: "This page's code",
            state: "pass",
            detail: `Current (engine ${ENGINE_VERSION}, built ${__BUILD_STAMP__}).`,
          }
        : {
            name: "This page's code",
            state: "fail",
            detail: `STALE — this tab runs engine ${ENGINE_VERSION} but the server runs ${body.engine_version ?? "unknown"}. Close this tab and open the site fresh.`,
          },
    );
  } catch {
    rows.push({
      name: "Reaching Palaestra",
      state: "fail",
      detail:
        "The request never got an answer. A network filter, VPN, or connectivity problem sits between this browser and the site.",
    });
    return rows;
  }

  // 3: cookies.
  try {
    document.cookie = "palaestra_probe=1; path=/; max-age=60; SameSite=Lax";
    const canWrite = document.cookie.includes("palaestra_probe=1");
    document.cookie = "palaestra_probe=; path=/; max-age=0";
    rows.push({
      name: "Cookies",
      state: canWrite ? "pass" : "fail",
      detail: canWrite
        ? "This browser lets the site keep a session."
        : "Blocked — sign-in cannot persist. Allow cookies for palaestra.thrivetech.ai.",
    });
  } catch {
    rows.push({ name: "Cookies", state: "fail", detail: "Blocked — sign-in cannot persist." });
  }

  // 4: the session, stated as fact rather than judged.
  try {
    const me = await fetch("/api/auth/me", { credentials: "include" });
    const body: { player?: { display_name?: string | null } | null } = await me.json();
    rows.push({
      name: "Signed in",
      state: "info",
      detail: body.player
        ? `Yes — as ${body.player.display_name ?? "a player"}.`
        : "Not on this browser. Playing starts with Sign in with LinkedIn.",
    });
  } catch {
    rows.push({ name: "Signed in", state: "fail", detail: "The identity check did not answer." });
  }

  return rows;
}

function ConnectionCheck() {
  const [rows, setRows] = useState<CheckRow[] | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    void runChecks().then((r) => {
      for (const row of r) recordTrace("breadcrumb", `connection-check ${row.name}: ${row.detail}`);
      setRows(r);
    });
  }, []);

  const mark = { pass: "✓", fail: "✕", info: "·" } as const;
  const tone = { pass: "text-ok", fail: "text-danger", info: "text-ink-mute" } as const;

  return (
    <Page
      title="Connection check"
      subtitle="What is working from this browser, right now — screenshot this page if anyone asks."
    >
      <div className="max-w-2xl rounded-lg border border-line bg-surface-1 p-6">
        {rows === null ? (
          <p className="text-sm text-ink-mute">Checking…</p>
        ) : (
          <ul className="space-y-3">
            {rows.map((r) => (
              <li key={r.name} className="flex items-start gap-3 text-sm">
                <span aria-hidden className={`font-mono text-base font-bold ${tone[r.state]}`}>
                  {mark[r.state]}
                </span>
                <span>
                  <strong className="text-ink">{r.name}.</strong>{" "}
                  <span className="text-ink-mute">{r.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
        {rows && (
          <div className="mt-5 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => {
                const text = rows.map((r) => `${mark[r.state]} ${r.name}: ${r.detail}`).join("\n");
                void navigator.clipboard.writeText(text).then(() => setCopied(true));
              }}
              className="rounded-md border border-line bg-surface-2 px-3 py-1.5 text-sm font-medium text-ink-mute hover:text-ink"
            >
              {copied ? "Copied" : "Copy the results"}
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-md border border-line bg-surface-2 px-3 py-1.5 text-sm font-medium text-ink-mute hover:text-ink"
            >
              Run it again
            </button>
            {/* The envelope, on the page that names it (#336). This screen is
                handed to somebody who is stuck, who is often signed out
                because signing in is what failed; telling them their results
                travel inside a report and offering no way to send one is a
                dead end at the moment of highest need. Works signed out. */}
            <SupportButton
              label="Send this to support"
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-surface-1 hover:opacity-90"
            />
          </div>
        )}
        <p className="mt-4 text-xs text-ink-dim">
          These results stay in this browser's memory. They leave it only if you send them,
          using the button above.
        </p>
      </div>
    </Page>
  );
}
