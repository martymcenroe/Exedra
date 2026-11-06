// GENERATED from martymcenroe/Palaestra by tools/export_exedra.py (#323). Do not edit it here: a change made here is overwritten by the next export and fails the drift test. Change it upstream, or open an issue with a scenario pack that shows the problem.

/**
 * The do-nothing baseline is the engine's (#665). Every score is reported
 * against `scoring.baseline_cost_usd`: "vs baseline", the stars' ratio, the
 * board. A wrong denominator would make every one of them wrong, and nothing
 * used to check it. The compiler writes the figure for each catalogue
 * scenario by its own arithmetic, one formula per scenario, and a contributed
 * pack states it by hand.
 *
 * So the engine settles it: a player who does nothing (no curtailment, no
 * battery, no generator, no commitment, no supply choice) must be charged
 * exactly the published baseline. That is the definition `engine.test.ts`
 * holds the fixture pack to, applied to every pack in the catalogue and to
 * anything tools/verify_pack.py has staged for review, by the same code, so
 * the catalogue and the gate cannot disagree.
 */

import { describe, expect, it } from "vitest";

import { replay, type Action } from "../shared/engine";
import type { ScenarioPack } from "../shared/pack";

const NOOP: Action = { curtail_mw: 0, battery_mw: 0, diesel_mw: 0 };

// The same two globs as optimal.test.ts: the catalogue, plus the gate's
// staged candidate, which is normally absent.
const packModules = {
  ...import.meta.glob<ScenarioPack>("../../data-g/packs/*.pack.json", {
    eager: true,
    import: "default",
  }),
  ...import.meta.glob<ScenarioPack>("../../data/verify-candidates/*.pack.json", {
    eager: true,
    import: "default",
  }),
};

const basename = (path: string) => path.slice(path.lastIndexOf("/") + 1);

const packs = Object.entries(packModules)
  .map(([path, pack]) => ({ file: basename(path), pack }))
  .sort((a, b) => a.file.localeCompare(b.file));

/** Cents, the unit the baseline is published in. */
const cents = (usd: number) => Math.round(usd * 100);

/** A dollar figure as the gate prints one: $168,300.00. */
const dollars = (usd: number) =>
  `$${usd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

describe("the baseline is what doing nothing costs", () => {
  it("has packs to check", () => {
    // A suite that silently found nothing would pass forever.
    expect(packs.length).toBeGreaterThan(0);
  });

  for (const { file, pack } of packs) {
    it(`${file} costs its published baseline when the player does nothing`, () => {
      const final = replay(
        pack,
        Array.from({ length: pack.turns }, () => NOOP),
      );
      const stated = pack.scoring.baseline_cost_usd;
      expect(
        cents(final.cost_usd),
        `baseline: the pack states ${dollars(stated)}, doing nothing costs ${dollars(final.cost_usd)}`,
      ).toBe(cents(stated));
    });
  }
});
