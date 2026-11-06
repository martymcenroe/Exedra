/**
 * A fuel supply option's deliveries in words (#469), shared by the play
 * screen and the local runner so the two never describe the same terms
 * differently. Pure, with a type-only import, so Node runs it directly.
 */

import type { SupplyOption } from "./pack";

/** An option's deliveries as runs of equal MW, in the pack's own numbers.
 * `at` labels a turn; on an episode longer than a day it names the day. */
export function availability(option: SupplyOption, gasMw: number, at: (turn: number) => string): string {
  const mw = option.available_mw;
  if (mw.every((x) => x >= gasMw)) return `the full ${gasMw} MW every turn`;
  const runs: string[] = [];
  let start = 0;
  for (let t = 1; t <= mw.length; t++) {
    if (t === mw.length || mw[t] !== mw[start]) {
      const amount = mw[start]! === 0 ? "none" : `${Math.min(mw[start]!, gasMw)} MW`;
      runs.push(`${amount} ${at(start)}–${at(t)}`);
      start = t;
    }
  }
  return runs.join(", ");
}
