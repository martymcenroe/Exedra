// GENERATED from martymcenroe/Palaestra by tools/export_exedra.py (#323). Do not edit it here: a change made here is overwritten by the next export and fails the drift test. Change it upstream, or open an issue with a scenario pack that shows the problem.

/**
 * The episode engine — the runtime half of the physics split (#26).
 *
 * Pure, deterministic, no I/O: (pack, state, action) -> (resolution, state').
 * Same pack + same actions -> identical records and score, always
 * (contract §8). The Worker is the only caller in production; tests and
 * the replay checker call it directly. Believable-not-certified energy
 * bookkeeping per contract §5 — heavier physics belongs in the offline
 * compiler, never here.
 *
 * Canonical merit order for serving campus load within a turn:
 *   curtailment -> battery discharge -> natural gas -> grid import.
 * (Display name "natural gas"; wire fields keep the legacy `diesel_*`
 * identifiers — renaming them would break stored episodes, #78.)
 * Discharge and gas are capped so they never exceed remaining load
 * (no export, no waste in v0); every cap is reported as a clamp note.
 */

import type {
  Commitment,
  FrozenObservationField,
  PackEvent,
  ScenarioPack,
  Stock,
  SystemStatus,
} from "./pack";

export const ENGINE_VERSION = "0.13.0";

export interface Action {
  curtail_mw: number;
  battery_mw: number; // + discharge, - charge
  diesel_mw: number;
  accept_offer?: boolean;
  /** Forward decisions (#464): commitment id -> MW, read only on that
   * commitment's decision turn. */
  commit?: Record<string, number>;
  /** The fuel supply option's id (#469), read only on turn 0. */
  supply?: string;
}

export type StockLevels = Record<string, number>;

export interface EngineState {
  turn: number;
  battery_soc_mwh: number;
  diesel_permit_hours: number;
  cost_usd: number;
  sla_shed_mwh: number;
  reliability_delivered_mwh: number;
  reliability_asked_mwh: number;
  /** Running neighbors' bill (#147); undefined on packs without its inputs. */
  others_cost_impact_usd?: number;
  stocks?: StockLevels;
  /** MW committed so far (#464), by commitment id; present on packs with commitments. */
  commitments?: Record<string, number>;
  /** The chosen fuel supply's id (#469), set on turn 0 of packs with supply options. */
  supply?: string;
  /** Gas hours run under an emergency order (#465); present on packs with one. */
  order_hours_used?: number;
  last_shown_price_usd_per_mwh?: number;
  last_shown_system_status?: SystemStatus;
  last_shown_forecast?: { price_usd_per_mwh: number; system_status: SystemStatus; fuel_usd_per_mwh?: number }[];
}

export interface Observation {
  turn: number;
  local_time: string;
  price_usd_per_mwh: number;
  system_status: SystemStatus;
  /** This hour's grid import limit (#467), on packs that carry one. Only the
   * current hour: when a feeder comes back is fog (#478). */
  import_limit_mw?: number;
  /** fuel_usd_per_mwh appears on packs with a fuel price series (#469). */
  forecast: { price_usd_per_mwh: number; system_status: SystemStatus; fuel_usd_per_mwh?: number }[];
  site: {
    it_demand_mw: number;
    battery_soc_mwh: number;
    diesel_permit_hours: number;
    stocks?: StockLevels;
    /** This hour's fuel price, on packs with a fuel price series (#469). */
    fuel_usd_per_mwh?: number;
    /** What the chosen supply can deliver this hour, once one is chosen (#469). */
    gas_available_mw?: number;
  };
  /** Each commitment's MW, or null before its decision turn (#464). */
  commitments?: Record<string, number | null>;
  /** The chosen supply's id, or null before turn 0 is played (#469). */
  supply?: string | null;
  events: PackEvent[];
  ledger: {
    cost_usd: number;
    sla_shed_mwh: number;
    reliability_delivered_mwh: number;
    reliability_asked_mwh: number;
    /** Gas hours run under an emergency order so far (#465), on packs with one. */
    order_hours_used?: number;
  };
  stale?: boolean;
  /** On a turn with frozen fields (#694): each frozen field, and the turn
   * whose values it repeats. Lets the screen say what is stale and since
   * when without seeing the pack's outage windows, which are fog. Absent,
   * with `stale`, for a field only a silent outage freezes (#697). */
  stale_as_of?: Partial<Record<FrozenObservationField, number>>;
}

export interface Resolution {
  applied: Action;
  clamped: boolean;
  clamp_notes: string[];
  grid_import_mw: number;
  turn_cost_usd: number;
  credit_usd: number;
  /** Price actually paid after grid response (#69); equals the strip price
   * for packs that declare no slope. */
  effective_price_usd_per_mwh: number;
  /** Grid response v1 (0004, #133): the hour's status graded from system
   * load INCLUDING your deviation. Present only when the pack declares
   * status_response — your relief can visibly downgrade an emergency, and
   * charging into the crunch can escalate one. Informational in v1: no
   * settlement arithmetic reads it, but the episode log records it, which
   * is the instrument value. Order events keying off realized status is
   * deferred to the cooperative-fleet work (see Iberia methodology). */
  realized_status?: SystemStatus;
  /** The neighbors' bill, this hour (#147): what your deviation did to the
   * cost of everyone ELSE's energy. slope · deviation · others' consumption.
   * Positive = you made the region's hour more expensive; negative = you
   * made it cheaper. Present only when the pack carries BOTH a price slope
   * (#69) and system load (#133) — its two inputs. First-order energy
   * component only; blind to capacity, transmission, and rate base, and
   * every display of it must say so. Informational: never enters your own
   * cost, so scoring and replay of legacy packs are untouched. */
  others_cost_impact_usd?: number;
  battery_soc_mwh: number;
  diesel_permit_hours: number;
  delivered_relief_mw: number;
  stocks?: StockLevels;
  /** This turn's commitment settlement (#464), included in turn_cost_usd:
   * imbalance and non-performance charges less any capacity payment.
   * Present only on packs with commitments. */
  commitment_usd?: number;
  /** The same, by commitment id. */
  commitment_settlement_usd?: Record<string, number>;
  /** This turn's premium for the chosen fuel supply (#469), included in
   * turn_cost_usd. Present only on packs with supply options. */
  supply_usd?: number;
  /** Gas hours run under an emergency order after this turn (#465). Present
   * only on packs with one. */
  order_hours_used?: number;
}

export interface Final {
  cost_usd: number;
  baseline_cost_usd: number;
  reliability_delivered_mwh: number;
  reliability_asked_mwh: number;
  /** The whole day's neighbors' bill (#147): what your operating choices
   * did to everyone else's energy cost, summed. Present only on packs
   * carrying both grid-response inputs; absent = legacy Final, bit-identical. */
  others_cost_impact_usd?: number;
  /** The day's gas hours run under an emergency order (#465): what the order
   * unlocked, and the emissions exposure it logged. Informational, never in
   * the cost. Present only on packs with an emergency order. */
  order_hours_used?: number;
}

const round2 = (x: number) => Math.round(x * 100) / 100;

export function applyStockDeliveries(
  stocks: Stock[],
  currentLevels: Record<string, number>,
  turn: number,
): Record<string, number> {
  const nextLevels = { ...currentLevels };
  for (const stock of stocks) {
    const delivery = stock.deliveries?.find((d) => d.turn === turn);
    if (delivery) {
      const current = nextLevels[stock.id] ?? 0;
      nextLevels[stock.id] = Math.min(stock.capacity, current + delivery.quantity);
    }
  }
  return nextLevels;
}

export function calculateStockClamp(
  stocks: Stock[],
  currentLevels: Record<string, number>,
  desiredDslMw: number,
  stepH: number,
): { clampedDslMw: number; bindingStockId?: string; wasClamped: boolean } {
  let bindingMw = desiredDslMw;
  let bindingStockId: string | undefined = undefined;

  for (const stock of stocks) {
    if (stock.burn_per_mwh_generated > 0) {
      const level = currentLevels[stock.id] ?? 0;
      const maxMwh = level / stock.burn_per_mwh_generated;
      const maxMw = maxMwh / stepH;
      if (maxMw < bindingMw) {
        bindingMw = Math.max(0, maxMw);
        bindingStockId = stock.id;
      }
    }
  }
  return {
    clampedDslMw: bindingMw,
    bindingStockId,
    wasClamped: bindingMw < desiredDslMw,
  };
}

export function applyStockBurn(
  stocks: Stock[],
  currentLevels: Record<string, number>,
  actualDslMw: number,
  stepH: number,
): Record<string, number> {
  const nextLevels = { ...currentLevels };
  for (const stock of stocks) {
    const burnAmount = actualDslMw * stepH * stock.burn_per_mwh_generated;
    const current = nextLevels[stock.id] ?? 0;
    nextLevels[stock.id] = Math.max(0, current - burnAmount);
  }
  return nextLevels;
}

export function compileForecast(
  pack: ScenarioPack,
  turn: number,
): { price_usd_per_mwh: number; system_status: SystemStatus; fuel_usd_per_mwh?: number }[] {
  const forecast: { price_usd_per_mwh: number; system_status: SystemStatus; fuel_usd_per_mwh?: number }[] = [];
  for (let h = 1; h <= 3; h++) {
    const ft = turn + h;
    if (ft < pack.turns) {
      const p = pack.grid.forecast?.price_usd_per_mwh?.[turn]?.[h - 1] ?? pack.grid.price_usd_per_mwh[ft]!;
      const s = pack.grid.forecast?.system_status?.[turn]?.[h - 1] ?? pack.grid.system_status[ft]!;
      const fuel = pack.site.diesel.fuel_usd_per_mwh_series?.[ft];
      forecast.push({
        price_usd_per_mwh: p,
        system_status: s,
        ...(fuel !== undefined && { fuel_usd_per_mwh: fuel }),
      });
    }
  }
  return forecast;
}

export function init(pack: ScenarioPack): EngineState {
  const stocks = pack.site.stocks
    ? Object.fromEntries(pack.site.stocks.map((s) => [s.id, s.initial]))
    : undefined;
  const initialShown = pack.grid.observation_outage
    ? {
        last_shown_price_usd_per_mwh: pack.grid.price_usd_per_mwh[0],
        last_shown_system_status: pack.grid.system_status[0],
        last_shown_forecast: compileForecast(pack, 0),
      }
    : {};
  return {
    turn: 0,
    battery_soc_mwh: pack.site.battery.energy_mwh * pack.site.battery.initial_soc,
    diesel_permit_hours: pack.site.diesel.permit_hours_remaining,
    cost_usd: 0,
    sla_shed_mwh: 0,
    reliability_delivered_mwh: 0,
    reliability_asked_mwh: 0,
    stocks,
    // Only packs with commitments carry the field, so every other pack's
    // state has exactly the keys it had under engine 0.6.0.
    ...(pack.commitments && { commitments: {} }),
    // The same for an emergency order (#465) and engine 0.9.0.
    ...(hasEmergencyOrder(pack) && { order_hours_used: 0 }),
    ...initialShown,
  };
}

/** Whether a pack carries an emergency order (#465): only those packs carry
 * `order_hours_used`, so every other pack is bit-identical to engine 0.9.0. */
function hasEmergencyOrder(pack: ScenarioPack): boolean {
  return pack.events.some((ev) => ev.type === "emergency_order");
}

/**
 * Whether an emergency order lifts the permit limit on a turn (#465): one is
 * active on the turn and its condition holds. `last_resort` reads the
 * published status strip, never the realized status, which depends on the
 * turn's own gas and is informational (0004 v1). The only place the
 * condition is evaluated: the engine passes the pack's events and strip, the
 * screen and the runner the observation's.
 */
export function orderInForce(events: PackEvent[], status: SystemStatus, turn: number): boolean {
  return events.some(
    (ev) =>
      ev.type === "emergency_order" &&
      ev.turns_active.includes(turn) &&
      (ev.condition === "always" || status === "emergency"),
  );
}

/** The clock, for anything that needs to name a turn's hour (#315). Widened
 * from `ScenarioPack` to the two fields it actually reads so the client can
 * call it with an episode view — one clock, so a second hand-rolled copy of
 * this arithmetic cannot drift from it. Type-only change; the runtime is
 * untouched and packs stay bit-identical. */
export function localTime(
  pack: Pick<ScenarioPack, "start_hour_local" | "step_minutes">,
  turn: number,
): string {
  const minutes = (pack.start_hour_local * 60 + turn * pack.step_minutes) % (24 * 60);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** Events visible at a turn: announced (ev.turn <= t) and not yet over. */
export function activeEvents(pack: ScenarioPack, turn: number): PackEvent[] {
  return pack.events.filter(
    (ev) => ev.turn <= turn && Math.max(...ev.turns_active) >= turn,
  );
}

/**
 * A nomination's free deviation at a turn (#635): a flow order in force names
 * it, otherwise the commitment's own term; 0 outside the window. The only
 * place the effective tolerance is computed. The engine passes the pack's
 * events; the screen and the runner pass the observation's, which hold every
 * flow order in force, because the compiler refuses one announced after its
 * first active turn.
 */
export function toleranceAt(c: Commitment, turn: number, events: PackEvent[]): number {
  const order = events.find(
    (ev) => ev.type === "flow_order" && ev.commitment === c.id && ev.turns_active.includes(turn),
  );
  if (order?.type === "flow_order") return order.tolerance_mw;
  const i = c.window.indexOf(turn);
  return i === -1 ? 0 : (c.tolerance_mw?.[i] ?? 0);
}

/** The MW a commitment stands at on a turn: on its decision turn, the
 * quantity named in this action, clamped as the settlement clamps it. */
function quantityAt(c: Commitment, t: number, state: EngineState, action: Action): number {
  if (c.decision_turn !== t) return state.commitments?.[c.id] ?? 0;
  const named = action.commit?.[c.id] ?? 0;
  return Number.isNaN(named) ? 0 : Math.min(Math.max(named, 0), c.max_mw);
}

function orderAt(pack: ScenarioPack, turn: number) {
  return pack.events.find(
    (ev): ev is Extract<PackEvent, { type: "curtailment_order" }> =>
      ev.type === "curtailment_order" && ev.turns_active.includes(turn),
  );
}

function appealAt(pack: ScenarioPack, turn: number) {
  return pack.events.find(
    (ev): ev is Extract<PackEvent, { type: "conservation_appeal" }> =>
      ev.type === "conservation_appeal" && ev.turns_active.includes(turn),
  );
}

function absorptionAt(pack: ScenarioPack, turn: number) {
  return pack.events.find(
    (ev): ev is Extract<PackEvent, { type: "absorption_appeal" }> =>
      ev.type === "absorption_appeal" && ev.turns_active.includes(turn),
  );
}

export function getNextShownFields(
  pack: ScenarioPack,
  state: EngineState,
): Pick<EngineState, "last_shown_price_usd_per_mwh" | "last_shown_system_status" | "last_shown_forecast"> {
  if (!pack.grid.observation_outage) return {};
  const obs = observe(pack, state);
  return {
    last_shown_price_usd_per_mwh: obs.price_usd_per_mwh,
    last_shown_system_status: obs.system_status,
    last_shown_forecast: obs.forecast,
  };
}

export function observe(pack: ScenarioPack, state: EngineState): Observation {
  const t = state.turn;
  const actualPrice = pack.grid.price_usd_per_mwh[t]!;
  const actualStatus = pack.grid.system_status[t]!;
  const actualForecast = compileForecast(pack, t);

  const frozenFields = frozenFieldsAt(pack, t);
  // What the screen is told (#697): only fields an announced outage freezes
  // are marked stale. A silent outage freezes its fields all the same.
  const announcedFields = frozenFieldsAt(pack, t, true);
  const isStale = announcedFields.size > 0;

  const shownPrice =
    frozenFields.has("price_usd_per_mwh") && state.last_shown_price_usd_per_mwh !== undefined
      ? state.last_shown_price_usd_per_mwh
      : actualPrice;

  const shownStatus =
    frozenFields.has("system_status") && state.last_shown_system_status !== undefined
      ? state.last_shown_system_status
      : actualStatus;

  const shownForecast =
    frozenFields.has("forecast") && state.last_shown_forecast !== undefined
      ? state.last_shown_forecast
      : actualForecast;

  const fuel = pack.site.diesel.fuel_usd_per_mwh_series;
  const options = pack.site.diesel.supply_options;
  const chosen = options?.find((o) => o.id === state.supply);
  return {
    turn: t,
    local_time: localTime(pack, t),
    price_usd_per_mwh: shownPrice,
    system_status: shownStatus,
    ...(pack.grid.import_limit_mw ? { import_limit_mw: pack.grid.import_limit_mw[t]! } : {}),
    forecast: shownForecast,
    site: {
      it_demand_mw: pack.site.it_load_mw[t]!,
      battery_soc_mwh: round2(state.battery_soc_mwh),
      diesel_permit_hours: state.diesel_permit_hours,
      ...(state.stocks ? { stocks: { ...state.stocks } } : {}),
      ...(fuel && { fuel_usd_per_mwh: fuel[t]! }),
      ...(chosen && { gas_available_mw: chosen.available_mw[t]! }),
    },
    ...(pack.commitments && {
      commitments: Object.fromEntries(
        pack.commitments.map((c) => [c.id, state.commitments?.[c.id] ?? null]),
      ),
    }),
    ...(options && { supply: state.supply ?? null }),
    events: activeEvents(pack, t),
    ledger: {
      cost_usd: round2(state.cost_usd),
      sla_shed_mwh: round2(state.sla_shed_mwh),
      reliability_delivered_mwh: round2(state.reliability_delivered_mwh),
      reliability_asked_mwh: round2(state.reliability_asked_mwh),
      ...(state.order_hours_used !== undefined && { order_hours_used: state.order_hours_used }),
    },
    ...(isStale && { stale: true, stale_as_of: staleAsOf(pack, t, announcedFields) }),
  };
}

/** The fields an observation outage freezes on turn `t` (#468), or, with
 * `announcedOnly`, only those an announced outage freezes (#697). */
function frozenFieldsAt(
  pack: ScenarioPack,
  t: number,
  announcedOnly = false,
): Set<FrozenObservationField> {
  const fields = new Set<FrozenObservationField>();
  for (const o of pack.grid.observation_outage ?? []) {
    if (announcedOnly && o.announced === false) continue;
    if (o.turns_active.includes(t)) for (const f of o.frozen_fields) fields.add(f);
  }
  return fields;
}

/** For each field frozen on turn `t`, the turn whose value it repeats (#694):
 * the last earlier turn on which that field was not frozen. A frozen field
 * shows what the previous turn showed, so this is where the chain ends. Turn
 * 0 is never frozen (the compiler refuses it), so every field has one. */
function staleAsOf(
  pack: ScenarioPack,
  t: number,
  frozen: Set<FrozenObservationField>,
): Partial<Record<FrozenObservationField, number>> {
  const asOf: Partial<Record<FrozenObservationField, number>> = {};
  for (const f of frozen) {
    let k = t - 1;
    while (k > 0 && frozenFieldsAt(pack, k).has(f)) k--;
    asOf[f] = k;
  }
  return asOf;
}

export function resolve(
  pack: ScenarioPack,
  state: EngineState,
  action: Action,
): { resolution: Resolution; next: EngineState } {
  const t = state.turn;
  if (t >= pack.turns) throw new Error(`episode over: turn ${t} >= ${pack.turns}`);

  const stepH = pack.step_minutes / 60;
  // Non-null by compile-time invariant (#243): validate_pack enforces every
  // per-turn array's length against `turns`, and the t < pack.turns guard
  // above bounds the index. The assertions are TYPE-only — any runtime
  // change here would break score(replay(log)) and every certified optimum.
  const it = pack.site.it_load_mw[t]!;
  const price = pack.grid.price_usd_per_mwh[t]!;
  const { battery, diesel, sla_usd_per_mwh_shed } = pack.site;
  const notes: string[] = [];

  let currentStocks = state.stocks ? { ...state.stocks } : undefined;
  if (pack.site.stocks && currentStocks) {
    currentStocks = applyStockDeliveries(pack.site.stocks, currentStocks, t);
  }

  // -- curtailment ----------------------------------------------------------
  const curtail = clamp(action.curtail_mw, 0, it, notes, "curtailment", "IT demand");

  // -- battery (signed: + discharge, - charge) ------------------------------
  let discharge = 0;
  let charge = 0;
  if (action.battery_mw >= 0) {
    discharge = clamp(action.battery_mw, 0, battery.power_mw, notes, "battery", "battery power");
    const socLimit = state.battery_soc_mwh / stepH;
    if (discharge > socLimit) {
      notes.push(`battery: discharge ${discharge} MW exceeds stored energy; clamped to ${round2(socLimit)}`);
      discharge = socLimit;
    }
    const remaining = it - curtail;
    if (discharge > remaining) {
      notes.push(`battery: discharge exceeds remaining load ${round2(remaining)} MW (no export in v0); clamped`);
      discharge = Math.max(0, remaining);
    }
  } else {
    charge = clamp(-action.battery_mw, 0, battery.power_mw, notes, "battery", "battery power");
    const headroom = (battery.energy_mwh - state.battery_soc_mwh) / battery.efficiency_rt / stepH;
    if (charge > headroom) {
      notes.push(`battery: charge ${charge} MW exceeds headroom; clamped to ${round2(headroom)}`);
      charge = headroom;
    }
  }

  // -- fuel supply (#469) -----------------------------------------------------
  // One arrangement, chosen on turn 0 and recorded in the applied action so
  // replay folds it; the first option is taken when none is named. Absent
  // `supply_options`, nothing here runs and gas supply is unlimited.
  const options = diesel.supply_options;
  let supply = state.supply;
  let supplyApplied: string | undefined;
  if (options) {
    if (t === 0) {
      const named = action.supply;
      const pick = options.find((o) => o.id === named);
      if (named === undefined) notes.push(`supply: none chosen; ${options[0]!.label}`);
      else if (!pick) notes.push(`supply: there is no option ${String(named)}; ${options[0]!.label}`);
      supply = (pick ?? options[0]!).id;
      supplyApplied = supply;
    } else if (action.supply !== undefined) {
      notes.push("supply: chosen on the first turn only; ignored");
    }
  }
  const option = options?.find((o) => o.id === supply);

  // -- natural gas (wire field: diesel_mw) ------------------------------------
  // An emergency order in force (#465) lifts the permit limit for the hour:
  // gas runs with no permit hours left, and the hour is counted against the
  // order instead of the permit. Absent an order, `waived` is false and this
  // is the 0.9.0 arithmetic exactly.
  const waived = orderInForce(pack.events, pack.grid.system_status[t]!, t);
  let dsl = clamp(action.diesel_mw, 0, diesel.power_mw, notes, "natural gas", "generator capacity");
  if (dsl > 0 && !waived && state.diesel_permit_hours <= 0) {
    notes.push("natural gas: no permit hours remaining; clamped to 0");
    dsl = 0;
  }
  if (option) {
    const available = option.available_mw[t]!;
    if (dsl > available) {
      notes.push(`natural gas: ${option.label} delivers ${round2(available)} MW this hour; clamped`);
      dsl = available;
    }
  }
  // A nomination that is all the gas there is (#635): no gas can be bought
  // above it plus this hour's tolerance. Absent `caps_gas`, nothing runs.
  for (const c of pack.commitments ?? []) {
    if (!c.caps_gas || !c.window.includes(t)) continue;
    const cap = quantityAt(c, t, state, action) + toleranceAt(c, t, pack.events);
    if (dsl > cap) {
      notes.push(`natural gas: the ${c.label.toLowerCase()} allows ${round2(cap)} MW this hour; clamped`);
      dsl = cap;
    }
  }
  const afterBattery = it - curtail - discharge;
  if (dsl > afterBattery) {
    notes.push(`natural gas: exceeds remaining load ${round2(afterBattery)} MW (no export in v0); clamped`);
    dsl = Math.max(0, afterBattery);
  }

  if (pack.site.stocks && currentStocks) {
    const stockClamp = calculateStockClamp(pack.site.stocks, currentStocks, dsl, stepH);
    if (stockClamp.wasClamped) {
      dsl = stockClamp.clampedDslMw;
      // The note is shown to the player beside the gas control (#268), so it
      // names the stock by its label and opens with the control's prefix.
      const binding = pack.site.stocks.find((s) => s.id === stockClamp.bindingStockId);
      const what = (binding?.label ?? stockClamp.bindingStockId ?? "stock").toLowerCase();
      notes.push(`natural gas: not enough ${what} left; clamped to ${round2(dsl)}`);
    }
    currentStocks = applyStockBurn(pack.site.stocks, currentStocks, dsl, stepH);
  }

  // -- energy balance & relief ----------------------------------------------
  const desiredGridImport = it - curtail - discharge - dsl + charge; // >= 0 by construction
  const importLimit = pack.grid.import_limit_mw?.[t];
  const gridImport = importLimit !== undefined ? Math.min(desiredGridImport, importLimit) : desiredGridImport;
  const forcedShed = desiredGridImport - gridImport;
  if (forcedShed > 0) {
    // Shown to the player (#478): the line, not a choice, shed this load.
    notes.push(
      `grid: the line carries ${round2(gridImport)} MW this hour; ${round2(forcedShed)} MW shed at the SLA rate`,
    );
  }
  const relief = Math.max(0, it - gridImport); // charging can push relief to 0, never below

  // -- reliability accounting -------------------------------------------------
  const order = orderAt(pack, t);
  let asked = 0;
  let delivered = 0;
  if (order) {
    asked = order.mw_requested * stepH;
    delivered = Math.min(relief, order.mw_requested) * stepH;
  }

  // -- commitments (#464) ------------------------------------------------------
  // A quantity named on a decision turn, then each window turn settled against
  // it. Nothing here touches the merit order: the gas, battery and grid above
  // are resolved exactly as before, and this only prices what they did. Absent
  // `commitments`, the whole block is skipped and nothing below reads it.
  let committed = state.commitments;
  let commitApplied: Record<string, number> | undefined;
  let commitmentUsd = 0;
  let settlement: Record<string, number> | undefined;
  if (pack.commitments) {
    committed = { ...(state.commitments ?? {}) };
    settlement = {};
    const open = new Set(pack.commitments.filter((c) => c.decision_turn === t).map((c) => c.id));
    for (const id of Object.keys(action.commit ?? {})) {
      if (!open.has(id)) notes.push(`commitment: ${id} is not open this turn; ignored`);
    }
    for (const c of pack.commitments) {
      let usd = 0;
      if (c.decision_turn === t) {
        const named = action.commit?.[c.id];
        if (named === undefined) notes.push(`commitment: ${c.label} not named; committed 0 MW`);
        const q = clamp(named ?? 0, 0, c.max_mw, notes, "commitment", `the ${c.label} maximum`);
        committed[c.id] = q;
        commitApplied = { ...(commitApplied ?? {}), [c.id]: q };
        if (c.kind === "demand_response") usd -= q * (c.capacity_usd_per_mw ?? 0);
      }
      const i = c.window.indexOf(t);
      if (i !== -1) {
        const q = committed[c.id] ?? 0;
        if (c.kind === "nomination") {
          const off = Math.max(0, Math.abs(dsl - q) - toleranceAt(c, t, pack.events));
          usd += off * (c.imbalance_usd_per_mwh ?? 0) * stepH;
        } else if (order) {
          usd += Math.max(0, q - relief) * (c.nonperformance_usd_per_mwh ?? 0) * stepH;
        }
      }
      if (usd !== 0) {
        settlement[c.id] = usd;
        commitmentUsd += usd;
      }
    }
  }

  // -- grid response (#69, contract §5 amendment) -----------------------------
  // The strip price is quoted at NOMINAL draw (serving full IT demand from
  // the grid). A pack may declare a per-turn slope; your deviation then
  // moves the price you pay: relief during scarcity earns a softer price,
  // charging into the cliff pays a harder one. Absent slope = price-taker,
  // bit-identical to engine v0.1.
  const slope = pack.grid.price_slope_usd_per_mwh_per_mw?.[t] ?? 0;
  const effectivePrice = price + slope * (gridImport - it);

  // -- status response (0004 v1, #133) ----------------------------------------
  // Grade the hour's realized status from system load plus the campus's
  // deviation. Absent field => undefined => the resolution is byte-identical
  // to prior engines (the dormancy guarantee, same pattern as the slope).
  const sr = pack.grid.status_response;
  let realizedStatus: SystemStatus | undefined;
  if (sr) {
    const sysLoad = sr.system_load_mw[t]! + (gridImport - it);
    realizedStatus =
      sysLoad >= sr.emergency_level_mw
        ? "emergency"
        : sysLoad >= sr.watch_level_mw
          ? "watch"
          : "normal";
  }

  // -- the neighbors' bill (#147) ---------------------------------------------
  // Your deviation moved the marginal price by slope · Δ; everyone else's
  // consumption (system load minus the campus at nominal) paid that movement.
  // Relief during scarcity is a negative number here: you made the region's
  // hour cheaper. First-order energy component only, and informational —
  // it never touches the player's own cost, so absent either input field
  // the resolution is byte-identical to prior engines.
  let othersImpact: number | undefined;
  if (sr && slope > 0) {
    const othersMw = sr.system_load_mw[t]! - it;
    othersImpact = slope * (gridImport - it) * othersMw * stepH;
  }

  // -- money ------------------------------------------------------------------
  // Supersession (#84 ruling, #183): a curtailment ORDER supersedes a
  // voluntary offer. On a turn inside both windows the reduction is
  // mandatory, so it counts toward the obligation above and earns no
  // voluntary credit — matching real programs, where compensation is for
  // what you were asked to volunteer, not for what you were told to do.
  //
  // Latent today: every live pack keeps the windows disjoint by
  // construction (see compile_s10's valley), so `order` is undefined on
  // every credited turn and this is bit-identical to engine 0.4.0. The
  // offline optimizers assert the same disjointness, so a pack that
  // overlaps them fails loudly at compile rather than shipping a gold line
  // the engine would not honour.
  const appeal = appealAt(pack, t);
  const reliefCredit =
    appeal && !order && action.accept_offer ? appeal.credit_usd_per_mwh * relief * stepH : 0;

  // -- absorption (#369) ------------------------------------------------------
  // The mirror of the appeal above. Absorption is draw ABOVE nominal, which is
  // what charging the battery produces, so the surplus lands in storage rather
  // than being spilled. Paid on the same accept_offer opt-in, because being
  // asked to consume is an offer like any other.
  //
  // An order supersedes this too, and for a sharper reason than it supersedes
  // the appeal: an order says reduce, absorption means draw more, so a turn
  // under both is a contradiction rather than a matter of pricing. The
  // compiler refuses to certify a pack that overlaps them.
  //
  // Dormant on every pack that carries no absorption_appeal: `absorb` is 0,
  // so `credit` equals the old expression exactly and the arithmetic is
  // bit-identical to engine 0.5.0.
  const absorption = absorptionAt(pack, t);
  const absorb = Math.max(0, gridImport - it);
  const absorptionCredit =
    absorption && !order && action.accept_offer
      ? absorption.credit_usd_per_mwh * absorb * stepH
      : 0;

  const credit = reliefCredit + absorptionCredit;
  // A fuel price series (#469) prices this turn's gas; absent, the scalar,
  // so the expression below is the 0.7.0 one exactly.
  const fuel = diesel.fuel_usd_per_mwh_series?.[t] ?? diesel.fuel_usd_per_mwh;
  const operatingCost =
    gridImport * effectivePrice * stepH +
    dsl * fuel * stepH +
    (curtail + forcedShed) * sla_usd_per_mwh_shed * stepH -
    credit;
  // Packs without commitments keep the 0.6.0 expression untouched (#464).
  const committedCost = pack.commitments ? operatingCost + commitmentUsd : operatingCost;
  // The chosen supply's premium is charged every turn (#469); packs without
  // supply options add nothing, and keep the 0.7.0 cost exactly.
  const supplyUsd = option ? option.premium_usd_per_turn : 0;
  const turnCost = option ? committedCost + supplyUsd : committedCost;

  const nextSoc = state.battery_soc_mwh - discharge * stepH + charge * battery.efficiency_rt * stepH;

  // Applied values stay full-precision: the log's applied actions are what
  // replay() folds, and score(replay(log)) === stored score is contractual.
  // Rounding is for display fields only.
  const applied: Action = {
    curtail_mw: curtail,
    battery_mw: discharge - charge, // exactly one is nonzero; avoids JS -0
    diesel_mw: dsl,
    ...(action.accept_offer !== undefined && { accept_offer: action.accept_offer }),
    // The clamped quantity, so replay() commits exactly what was settled.
    ...(commitApplied && { commit: commitApplied }),
    // The option actually taken, so replay() supplies exactly what was settled.
    ...(supplyApplied !== undefined && { supply: supplyApplied }),
  };

  const nextShown = getNextShownFields(pack, state);
  const next: EngineState = {
    turn: t + 1,
    battery_soc_mwh: nextSoc,
    diesel_permit_hours: state.diesel_permit_hours - (dsl > 0 && !waived ? 1 : 0),
    cost_usd: state.cost_usd + turnCost,
    sla_shed_mwh: state.sla_shed_mwh + (curtail + forcedShed) * stepH,
    reliability_delivered_mwh: state.reliability_delivered_mwh + delivered,
    reliability_asked_mwh: state.reliability_asked_mwh + asked,
    ...(othersImpact !== undefined && {
      others_cost_impact_usd: (state.others_cost_impact_usd ?? 0) + othersImpact,
    }),
    stocks: currentStocks ? { ...currentStocks } : undefined,
    ...(committed !== undefined && { commitments: committed }),
    ...(supply !== undefined && { supply }),
    ...(state.order_hours_used !== undefined && {
      order_hours_used: state.order_hours_used + (dsl > 0 && waived ? 1 : 0),
    }),
    ...nextShown,
  };

  const resolution: Resolution = {
    applied,
    clamped: notes.length > 0,
    clamp_notes: notes,
    grid_import_mw: round2(gridImport),
    turn_cost_usd: round2(turnCost),
    credit_usd: round2(credit),
    effective_price_usd_per_mwh: round2(effectivePrice),
    ...(realizedStatus !== undefined && { realized_status: realizedStatus }),
    ...(othersImpact !== undefined && { others_cost_impact_usd: round2(othersImpact) }),
    battery_soc_mwh: round2(nextSoc),
    diesel_permit_hours: next.diesel_permit_hours,
    delivered_relief_mw: round2(relief),
    stocks: currentStocks ? { ...currentStocks } : undefined,
    ...(settlement && {
      commitment_usd: round2(commitmentUsd),
      commitment_settlement_usd: Object.fromEntries(
        Object.entries(settlement).map(([id, usd]) => [id, round2(usd)]),
      ),
    }),
    ...(option && { supply_usd: round2(supplyUsd) }),
    ...(next.order_hours_used !== undefined && { order_hours_used: next.order_hours_used }),
  };

  return { resolution, next };
}

export function finalize(pack: ScenarioPack, state: EngineState): Final {
  if (state.turn < pack.turns) {
    throw new Error(`episode not over: turn ${state.turn} < ${pack.turns}`);
  }
  return {
    cost_usd: round2(state.cost_usd),
    baseline_cost_usd: pack.scoring.baseline_cost_usd,
    reliability_delivered_mwh: round2(state.reliability_delivered_mwh),
    reliability_asked_mwh: round2(state.reliability_asked_mwh),
    ...(state.others_cost_impact_usd !== undefined && {
      others_cost_impact_usd: round2(state.others_cost_impact_usd),
    }),
    ...(state.order_hours_used !== undefined && { order_hours_used: state.order_hours_used }),
  };
}

/** Fold a full action sequence into a Final — the replay function of
 * contract §7. score(replay(log)) === stored score is enforced by test. */
export function replay(pack: ScenarioPack, actions: Action[]): Final {
  let state = init(pack);
  for (const a of actions) state = resolve(pack, state, a).next;
  return finalize(pack, state);
}

function clamp(
  value: number,
  lo: number,
  hi: number,
  notes: string[],
  field: string,
  what: string,
): number {
  if (Number.isNaN(value)) {
    notes.push(`${field}: not a number; clamped to 0`);
    return Math.min(Math.max(0, lo), hi);
  }
  if (value < lo) {
    notes.push(`${field}: ${value} below ${lo}; clamped`);
    return lo;
  }
  if (value > hi) {
    notes.push(`${field}: ${value} exceeds ${what} (${round2(hi)}); clamped`);
    return hi;
  }
  return value;
}
