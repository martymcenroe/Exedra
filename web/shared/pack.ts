// GENERATED from martymcenroe/Palaestra by tools/export_exedra.py (#323). Do not edit it here: a change made here is overwritten by the next export and fails the drift test. Change it upstream, or open an issue with a scenario pack that shows the problem.

/**
 * Scenario pack types — the TypeScript mirror of
 * schema/scenario-pack.v0.schema.json (normative). Field names are
 * snake_case on purpose: these records cross the wire and land in episode
 * logs that validate against the JSON Schemas; the schema spelling wins.
 */

export type SystemStatus = "normal" | "watch" | "emergency";

export interface StockDelivery {
  turn: number;
  quantity: number;
}

export interface Stock {
  id: string;
  label: string;
  unit: string;
  initial: number;
  capacity: number;
  burn_per_mwh_generated: number;
  deliveries?: StockDelivery[];
}

export interface ConservationAppeal {
  turn: number;
  type: "conservation_appeal";
  credit_usd_per_mwh: number;
  turns_active: number[];
  notice_md?: string;
}

export interface CurtailmentOrder {
  turn: number;
  type: "curtailment_order";
  mw_requested: number;
  turns_active: number[];
  notice_md?: string;
}

/**
 * The mirror of a conservation appeal: an inducement to RAISE draw during a
 * surplus window (#369).
 *
 * Both older events mean reduce demand, so the engine could pose scarcity
 * questions and nothing else. An oversupply day is the other half of the
 * large-load interface question, and it is the half where the standards gap
 * sits: a data centre that can be ASKED TO CONSUME is a different regulatory
 * object from one that can only be curtailed.
 *
 * Absorption is draw above nominal IT demand, which the campus already has a
 * lever for. Charging the battery raises grid import above what the site
 * needs, so the surplus lands in storage instead of being spilled.
 */
export interface AbsorptionAppeal {
  turn: number;
  type: "absorption_appeal";
  credit_usd_per_mwh: number;
  turns_active: number[];
  notice_md?: string;
}

/**
 * Information only (#635): shown while active, and read by no arithmetic. A
 * pipeline's critical notice is one: it says the rules may change, and
 * changes nothing itself.
 */
export interface Notice {
  turn: number;
  type: "notice";
  turns_active: number[];
  notice_md: string;
}

/**
 * An operational flow order (#635). On each turn in `turns_active` the named
 * nomination settles against `tolerance_mw` in place of its own. A
 * commitment's terms are public from turn 0; an event is hidden until its
 * turn, which is what makes an OFO a change in the rules mid-game.
 */
export interface FlowOrder {
  turn: number;
  type: "flow_order";
  /** The id of the nomination it tightens. */
  commitment: string;
  tolerance_mw: number;
  turns_active: number[];
  notice_md?: string;
}

/**
 * An FPA 202(c) emergency order (#465): permission to run the gas plant past
 * its permit. On a turn in `turns_active` where the order's condition holds,
 * gas output spends no permit hour and is counted in the ledger's
 * `order_hours_used` instead: the hours the order unlocked are its value and
 * its emissions exposure. `last_resort` holds only on turns the published
 * status strip calls emergency; `always` holds on every active turn.
 *
 * `suspends_permit` is the only form built: the order lifts the limit for its
 * window. The form that adds a fixed number of hours is #644.
 */
export interface EmergencyOrder {
  turn: number;
  type: "emergency_order";
  suspends_permit: true;
  condition: "always" | "last_resort";
  turns_active: number[];
  notice_md?: string;
}

export type PackEvent =
  | ConservationAppeal
  | CurtailmentOrder
  | AbsorptionAppeal
  | Notice
  | FlowOrder
  | EmergencyOrder;

export type FrozenObservationField = "price_usd_per_mwh" | "system_status" | "forecast";

export interface ObservationOutage {
  turns_active: number[];
  frozen_fields: FrozenObservationField[];
  /** Whether the screen is told (#697). Absent or true: the observation marks
   * the frozen fields stale (#694). False: they still repeat their last
   * values, but nothing on the observation says so. */
  announced?: boolean;
}

/**
 * A quantity promised ahead of a window, then settled against what was
 * delivered (#464). The player names the quantity on `decision_turn` through
 * Action.commit; each turn in `window` is then settled against it.
 *
 * - `nomination`: a flat natural-gas MW for the window, the way a pipeline
 *   takes a ratable nomination. Each turn's gas output above or below it,
 *   beyond that turn's tolerance, is charged `imbalance_usd_per_mwh`. An
 *   operational flow order that cuts the tolerance mid-window is a
 *   `flow_order` event (#635), because these terms are public from turn 0.
 *   Under `caps_gas` the nomination is all the gas there is: output above it
 *   plus the tolerance cannot be bought, and is clamped.
 * - `demand_response`: MW of relief enrolled for the window, paid
 *   `capacity_usd_per_mw` on the decision turn. On each window turn under a
 *   curtailment order, delivered relief below the enrolment is charged
 *   `nonperformance_usd_per_mwh`, on top of ordinary reliability accounting.
 */
export interface Commitment {
  id: string;
  kind: "nomination" | "demand_response";
  label: string;
  decision_turn: number;
  /** Turns settled against the quantity, ascending, none before decision_turn. */
  window: number[];
  max_mw: number;
  notice_md?: string;
  /** nomination: charged per MWh of gas output outside tolerance. */
  imbalance_usd_per_mwh?: number;
  /** nomination: free deviation per window turn, aligned with `window`; absent = 0. */
  tolerance_mw?: number[];
  /** nomination: gas output is capped at the nomination plus this turn's tolerance (#635). */
  caps_gas?: boolean;
  /** demand_response: paid per enrolled MW on the decision turn. */
  capacity_usd_per_mw?: number;
  /** demand_response: charged per MWh of shortfall on an ordered window turn. */
  nonperformance_usd_per_mwh?: number;
}

/**
 * A fuel supply arrangement (#469), chosen once at turn 0 through
 * Action.supply. The choice costs `premium_usd_per_turn` every turn and caps
 * gas output at `available_mw[t]`: firm supply pays a premium and is there
 * every turn; spot is free until a turn with nothing to buy.
 */
export interface SupplyOption {
  id: string;
  label: string;
  premium_usd_per_turn: number;
  /** MW of gas the arrangement can deliver each turn; length = turns. */
  available_mw: number[];
}

/**
 * Scenario id namespaces (#214, design 0007). `S-nn` is the curated
 * catalogue; `C-nnn` is the contributed library. The pattern is normative in
 * schema/scenario-pack.v0.schema.json and mirrored here ONCE — it previously
 * existed as four separate literals across the worker, which is the drift
 * this repo has been burned by before.
 */
const SCENARIO_ID = /^(S-\d{2}|C-\d{3})$/;

/** Whether a string is a well-formed scenario id in either namespace. */
export const isScenarioId = (id: string): boolean => SCENARIO_ID.test(id);

/**
 * Contributed scenarios sit OUTSIDE the catalogue's difficulty ordering
 * (#126) rather than inside it, because no contributed set can satisfy
 * "strictly harder than the last" and that rule must not be weakened to
 * accommodate them. A shelf, not a rung.
 */
export const isContributed = (id: string): boolean => id.startsWith("C-");

/** A named contributor (#214). Required on contributed C-nnn packs. */
export interface PackAuthor {
  name: string;
  affiliation: string;
  orcid?: string;
}

/**
 * Where the numbers came from. Open-ended by design — the schema allows
 * additional keys — but the fields the library surface and the acceptance
 * gate rely on are named here.
 */
export interface Provenance {
  source?: string;
  region?: string;
  source_day?: string;
  notes?: string;
  /** The operator's published dataset, so a reader can go and check. */
  source_url?: string;
  /** Named licence; the contributor attests it permits redistribution (#217). */
  source_license?: string;
  /** Workshop and host institution this pack came from, if any. */
  cohort?: string;
  authors?: PackAuthor[];
  /**
   * What the published load series actually counts (#221). Present whenever
   * grid.status_response is: the community reading divides the neighbours'
   * bill across others' consumption derived from that series, so an unstated
   * exclusion understates the denominator. An empty `excluded` means the
   * question was asked; absence means nobody asked.
   */
  system_load_scope?: {
    excluded: string[];
    included?: string[];
    definition_url?: string;
  };
  [key: string]: unknown;
}

export interface ScenarioPack {
  pack_version: string;
  scenario_id: string;
  title: string;
  substrate: string;
  provenance?: Provenance;
  brief_md: string;
  /** Per-turn paidotribes lines; presence marks a tutorial pack. */
  coach_md?: string[];
  step_minutes: number;
  turns: number;
  start_hour_local: number;
  site: {
    name: string;
    it_load_mw: number[];
    sla_usd_per_mwh_shed: number;
    battery: {
      power_mw: number;
      energy_mwh: number;
      efficiency_rt: number;
      initial_soc: number;
    };
    diesel: {
      power_mw: number;
      permit_hours_remaining: number;
      fuel_usd_per_mwh: number;
      /** Optional fuel price per turn (#469), overriding fuel_usd_per_mwh.
       * Absent = the scalar every turn, bit-identical to engine 0.7.0. */
      fuel_usd_per_mwh_series?: number[];
      /** Optional supply arrangements (#469), one chosen at turn 0. Absent =
       * unlimited supply at no premium, bit-identical to engine 0.7.0. */
      supply_options?: SupplyOption[];
    };
    stocks?: Stock[];
  };
  grid: {
    /** Price at NOMINAL campus draw (see price_slope for grid response). */
    price_usd_per_mwh: number[];
    system_status: SystemStatus[];
    /** Optional grid response (#69): $/MWh change per MW of deviation from
     * nominal draw. Absent = price-taker, bit-identical to engine v0.1. */
    price_slope_usd_per_mwh_per_mw?: number[];
    import_limit_mw?: number[];
    /** Optional grid response v1 (0004, #133): when present the engine
     * grades each hour's REALIZED status from system load including the
     * campus's deviation. Absent = the static strip stands alone. */
    status_response?: {
      system_load_mw: number[];
      watch_level_mw: number;
      emergency_level_mw: number;
    };
    /** Optional grid response v2 (0004, #134): honest forecasts as data.
     * forecast.price_usd_per_mwh[t][h] is what the player SEES at turn t
     * for turn t+1+h; actuals stay authoritative for settlement. The error
     * model is documented in provenance — the fog is data, never RNG. */
    forecast?: {
      price_usd_per_mwh: number[][];
      system_status?: SystemStatus[][];
    };
    /** Optional observation outages (#468) freezing specified fields. */
    observation_outage?: ObservationOutage[];
  };
  /** Position in the binding difficulty ordering (#126), 0 = easiest.
   * Presentation metadata only; absent packs sort last. */
  difficulty_rank?: number;
  /** Optional curriculum gate (#144, design 0005): concepts a player must
   * have established before starting this scenario. Absent = open to all,
   * bit-identical behavior for every existing pack. */
  requires_concepts?: string[];
  events: PackEvent[];
  /** Optional forward decisions (#464). Absent = no forward decisions, and
   * settlement is bit-identical to engine 0.6.0. */
  commitments?: Commitment[];
  scoring: {
    score_version: string;
    baseline_cost_usd: number;
    /** Compiler-solved exact minimum among fully-delivering plays (#93);
     * absent on grid-response packs. Stars measure against it. */
    optimal_cost_usd?: number;
    metrics: {
      id: "cost" | "reliability";
      label: string;
      direction: "minimize" | "maximize";
      unit: string;
    }[];
  };
}

/** A stock as the player's screen receives it: everything but its deliveries. */
export type StockView = Omit<Stock, "deliveries">;
type Diesel = ScenarioPack["site"]["diesel"];
export type SiteView = Omit<ScenarioPack["site"], "stocks" | "diesel"> & {
  diesel: Omit<Diesel, "fuel_usd_per_mwh_series">;
  stocks?: StockView[];
};

/**
 * The site as the server sends it to the player (#440). A stock's deliveries
 * record when a refill actually arrives, and a brief may promise a different
 * turn: S-11's refill is promised for dawn on day two and comes after the
 * third evening. So the deliveries stay on the server, and the player learns
 * of one when the level rises. Each stock is copied field by field, so a field
 * added to Stock later reaches the screen only once it is named here.
 *
 * A fuel price series (#469) stays on the server too: the observation carries
 * this hour's fuel price and the forecast the next three, as for grid prices.
 * Supply options are terms, like a commitment's, and go to the screen.
 *
 * A site with neither stocks nor a fuel series is returned as it is, so every
 * other pack's payload is unchanged.
 */
export function siteView(site: ScenarioPack["site"]): SiteView {
  if (!site.stocks && !site.diesel.fuel_usd_per_mwh_series) return site;
  const diesel: Diesel = { ...site.diesel };
  delete diesel.fuel_usd_per_mwh_series;
  if (!site.stocks) return { ...site, diesel };
  return {
    ...site,
    diesel,
    stocks: site.stocks.map((s) => ({
      id: s.id,
      label: s.label,
      unit: s.unit,
      initial: s.initial,
      capacity: s.capacity,
      burn_per_mwh_generated: s.burn_per_mwh_generated,
    })),
  };
}
