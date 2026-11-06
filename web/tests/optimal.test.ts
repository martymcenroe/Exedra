// GENERATED from martymcenroe/Palaestra by tools/export_exedra.py (#323). Do not edit it here: a change made here is overwritten by the next export and fails the drift test. Change it upstream, or open an issue with a scenario pack that shows the problem.

/**
 * Gold-line parity (#93): every published optimum must be ACHIEVABLE in the
 * real engine, exactly — otherwise gold is a lie (unreachable) or a scandal
 * (beatable). Each pack's optimal_cost_usd is replayed here to the penny,
 * with full relief required.
 *
 * The line replayed is the solver's OWN argmin, written out by the compiler
 * as data (#212, design 0007). It used to be transcribed into this file by
 * hand, one block per pack, with the reasoning in a comment. That worked for
 * the packs one person had solved personally and does not extend to
 * scenarios arriving from outside, which is the contribution path this
 * catalogue is about to grow.
 *
 * So this file no longer names any scenario. It globs data-g/plans/, replays
 * whatever it finds, and separately insists that every pack claiming an
 * optimum has a plan behind it.
 */

import { describe, expect, it } from "vitest";

import { replay, type Action } from "../shared/engine";
import type { ScenarioPack } from "../shared/pack";

/** The compiler's certification record for one scenario. */
interface CertifiedPlan {
  scenario_id: string;
  pack_version: string;
  score_version: string;
  /** Which optimizer proved it: "enumerator" or "milp". */
  solver: string;
  optimal_cost_usd: number;
  /** The argmin as engine actions, ready to replay. */
  line: Action[];
}

// The catalogue, plus anything tools/verify_pack.py has staged for review
// (#213). A candidate under review is held to the SAME parity rule as a
// published scenario, by the same code, because two definitions of "the gold
// line is real" would disagree within a month. The staging directory is
// normally absent and the glob then contributes nothing.
const planModules = {
  ...import.meta.glob<CertifiedPlan>("../../data-g/plans/*.plan.json", {
    eager: true,
    import: "default",
  }),
  ...import.meta.glob<CertifiedPlan>("../../data/verify-candidates/*.plan.json", {
    eager: true,
    import: "default",
  }),
};
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

const plans = Object.entries(planModules)
  .map(([path, plan]) => ({ file: basename(path), plan }))
  .sort((a, b) => a.file.localeCompare(b.file));

const packsById = new Map(Object.values(packModules).map((p) => [p.scenario_id, p]));

describe("the gold line is real", () => {
  it("has plans to check", () => {
    // A parity suite that silently found nothing would pass forever.
    expect(plans.length).toBeGreaterThan(0);
  });

  for (const { file, plan } of plans) {
    it(`${file} replays to its published optimum`, () => {
      const pack = packsById.get(plan.scenario_id);
      expect(pack, `no pack for ${plan.scenario_id}`).toBeDefined();
      if (!pack) return;

      // Plan and pack are separate artifacts and can drift apart; a stale
      // plan replaying to its own stale number would prove nothing.
      expect(plan.optimal_cost_usd).toBe(pack.scoring.optimal_cost_usd);
      expect(plan.pack_version).toBe(pack.pack_version);
      expect(plan.score_version).toBe(pack.scoring.score_version);
      expect(plan.line).toHaveLength(pack.turns);

      const final = replay(pack, plan.line);
      expect(final.cost_usd).toBeCloseTo(pack.scoring.optimal_cost_usd!, 1);
      expect(final.reliability_delivered_mwh).toBeCloseTo(final.reliability_asked_mwh, 6);
    });
  }

  it("every pack that claims an optimum has a plan proving it", () => {
    // Coverage runs from the packs, not the plans: deleting a plan must fail
    // the suite rather than quietly shrinking what gets checked. A pack with
    // no optimum (S-09 carries a price slope, which both optimizers refuse)
    // is expected to have none, and awards no stars.
    const certified = [...packsById.values()]
      .filter((p) => p.scoring.optimal_cost_usd !== undefined)
      .map((p) => p.scenario_id)
      .sort();
    const proven = plans.map(({ plan }) => plan.scenario_id).sort();
    expect(proven).toEqual(certified);
  });
});
