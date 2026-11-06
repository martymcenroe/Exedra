// GENERATED from martymcenroe/Palaestra by tools/export_exedra.py (#323). Do not edit it here: a change made here is overwritten by the next export and fails the drift test. Change it upstream, or open an issue with a scenario pack that shows the problem.

/**
 * Scoring v1 (#27): versioned, published, replayable.
 *
 * Exactly two metrics in tension (vision §5) and every number carries its
 * denominator (ADR 0001). The score is a pure function of the episode's
 * Final — which is itself a pure function of (pack, actions) via
 * engine.replay(). Arguing with this file is the instrument working.
 */

import type { Final } from "./engine";
import type { ScenarioPack } from "./pack";

export interface Score {
  score_version: string;
  cost: {
    value_usd: number;
    baseline_usd: number;
    /** value / baseline — below 1.0 beat doing nothing. */
    vs_baseline: number;
  };
  reliability: {
    delivered_mwh: number;
    asked_mwh: number;
    /** delivered / asked; a perfect 1.0 means every asked MWh was served. */
    ratio: number;
  };
}

const round2 = (x: number) => Math.round(x * 100) / 100;
const round4 = (x: number) => Math.round(x * 10000) / 10000;

export type Star = "ribbon" | "gold" | "silver" | "bronze";

/** Star thresholds, exported so the public scoring page (#11) displays the
 * same numbers this function enforces — one source, no drift.
 *
 * Re-oriented 2026-07-29 (#165, operator-decreed): the original ladder
 * (bronze 2%, silver 1%, gold penny) measured multiplicatively against the
 * optimal and left a 2.92%-above-optimal run — an excellent day's play —
 * with nothing. Integer percents now step the whole ladder, and penny-exact
 * gets its own tier above gold: the Blue Ribbon. */
export const STAR_RULES = {
  /** Blue Ribbon: match the solved optimal to the penny. */
  ribbon_tolerance_usd: 0.01,
  /** Gold: within 1% of the solved optimal. */
  gold_within: 0.01,
  /** Silver: within 2% of the solved optimal. */
  silver_within: 0.02,
  /** Bronze: within 3% of the solved optimal. */
  bronze_within: 0.03,
} as const;

/** Stars (#93, re-laddered #165): bronze within 3% of the pack's computed
 * optimal, silver 2%, gold 1%, Blue Ribbon = the optimal line itself
 * (penny tolerance). Full relief delivery required for any tier — a cheap
 * run that shirks the order never medals. Null when the pack carries no
 * optimal (grid-response packs) or thresholds are missed. */
export function starFor(pack: ScenarioPack, final: Final): Star | null {
  const opt = pack.scoring.optimal_cost_usd;
  if (opt === undefined) return null;
  if (final.reliability_asked_mwh > 0 && final.reliability_delivered_mwh < final.reliability_asked_mwh - 1e-6)
    return null;
  if (final.cost_usd <= opt + STAR_RULES.ribbon_tolerance_usd) return "ribbon";
  if (final.cost_usd <= opt * (1 + STAR_RULES.gold_within)) return "gold";
  if (final.cost_usd <= opt * (1 + STAR_RULES.silver_within)) return "silver";
  if (final.cost_usd <= opt * (1 + STAR_RULES.bronze_within)) return "bronze";
  return null;
}

/** The board's ordering, in one place (#109).
 *
 * Boards rank RUNS, not players (#91): highest reliability first, then lowest
 * cost-vs-baseline. Every consumer must agree on this exactly — the board
 * itself, a player's rank within it, and the "someone passed you" check
 * (#107) are the same question asked three ways. A second, drifting copy of
 * this comparator would let a player be told they were passed by a run the
 * board shows below them.
 *
 * @returns true when `a` outranks `b`.
 */
export function betterScore(a: Score, b: Score): boolean {
  return a.reliability.ratio !== b.reliability.ratio
    ? a.reliability.ratio > b.reliability.ratio
    : a.cost.vs_baseline < b.cost.vs_baseline;
}

export function computeScore(pack: ScenarioPack, final: Final): Score {
  const baseline = pack.scoring.baseline_cost_usd;
  return {
    score_version: pack.scoring.score_version,
    cost: {
      value_usd: round2(final.cost_usd),
      baseline_usd: baseline,
      vs_baseline: round4(baseline !== 0 ? final.cost_usd / baseline : 1),
    },
    reliability: {
      delivered_mwh: round2(final.reliability_delivered_mwh),
      asked_mwh: round2(final.reliability_asked_mwh),
      ratio: round4(
        final.reliability_asked_mwh > 0
          ? final.reliability_delivered_mwh / final.reliability_asked_mwh
          : 1,
      ),
    },
  };
}
