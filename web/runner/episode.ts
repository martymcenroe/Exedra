/**
 * The local runner's episode (#328): one scenario played in memory, with no
 * database, no account, no secrets and no network.
 *
 * It drives the engine the venue runs (../shared/engine.ts, never a copy)
 * through the sequence the venue's turn endpoint follows: observe, resolve,
 * record the APPLIED action, and after the last turn finalize and score with
 * the published scoring function. The log it keeps has the venue's shape, so
 * computeScore(replay(log)) scores it exactly as the venue would score the
 * same pack and the same actions. tests/runner.test.ts asserts that.
 *
 * Pure: no I/O. The command line around it is play.ts. Imports name their
 * .ts files so Node can run this directly, with no build step.
 */

import {
  ENGINE_VERSION,
  finalize,
  init,
  observe,
  resolve,
  type Action,
  type EngineState,
  type Final,
  type Observation,
  type Resolution,
} from "../shared/engine.ts";
import type { ScenarioPack } from "../shared/pack.ts";
import { computeScore, starFor, type Score, type Star } from "../shared/scoring.ts";

/** A refusal the runner can explain: bad input, an unplayable pack, a turn
 * out of order. The command line prints the message and exits non-zero. */
export class RunnerError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RunnerError";
  }
}

/** One turn as the venue's log records it (contract §8). */
export interface TurnRecord {
  idx: number;
  observation: Observation;
  /** The applied action, as the venue stores it: what replay() folds. */
  action: Action;
  resolution: Resolution;
}

export interface Player {
  id: string;
  kind: "human" | "agent";
}

/** The venue's episode log shape (GET /api/episodes/:id/log). */
export interface EpisodeLog {
  episode_id: string;
  scenario_id: string;
  pack_version: string;
  engine_version: string;
  score_version: string;
  started_at: string;
  completed_at?: string;
  player: Player;
  turns: TurnRecord[];
  final?: Final;
}

/** What the venue computes when the last turn lands. */
export interface Settlement {
  final: Final;
  score: Score;
  star: Star | null;
}

export interface EpisodeOptions {
  player: Player;
  episodeId?: string;
  /** ISO timestamps for the log; replaceable so a test can pin them. */
  clock?: () => string;
}

export class LocalEpisode {
  readonly pack: ScenarioPack;
  readonly log: EpisodeLog;
  private state: EngineState;
  private settled: Settlement | null = null;
  private readonly clock: () => string;

  constructor(pack: ScenarioPack, options: EpisodeOptions) {
    this.pack = pack;
    this.clock = options.clock ?? (() => new Date().toISOString());
    this.state = init(pack);
    this.log = {
      episode_id: options.episodeId ?? crypto.randomUUID(),
      scenario_id: pack.scenario_id,
      pack_version: pack.pack_version,
      engine_version: ENGINE_VERSION,
      score_version: pack.scoring.score_version,
      started_at: this.clock(),
      player: options.player,
      turns: [],
    };
  }

  /** The turn about to be played, counted from 0 as the engine counts it. */
  get turn(): number {
    return this.state.turn;
  }

  get over(): boolean {
    return this.state.turn >= this.pack.turns;
  }

  /** Null until the last turn has been played. */
  get settlement(): Settlement | null {
    return this.settled;
  }

  observation(): Observation {
    if (this.over) throw new RunnerError("the episode is over, so there is nothing left to observe");
    return observe(this.pack, this.state);
  }

  play(action: Action): { resolution: Resolution; settlement: Settlement | null } {
    if (this.over) throw new RunnerError("the episode is over, so no further action can be played");
    const observation = observe(this.pack, this.state);
    const { resolution, next } = resolve(this.pack, this.state, action);
    this.log.turns.push({
      idx: this.state.turn,
      observation,
      action: resolution.applied,
      resolution,
    });
    this.state = next;
    if (next.turn >= this.pack.turns) {
      const final = finalize(this.pack, next);
      this.settled = { final, score: computeScore(this.pack, final), star: starFor(this.pack, final) };
      this.log.completed_at = this.clock();
      this.log.final = final;
    }
    return { resolution, settlement: this.settled };
  }
}

// -- reading actions ------------------------------------------------------------

const ACCEPT = new Set(["accept", "yes", "y", "true"]);
const DECLINE = new Set(["decline", "no", "n", "false"]);

/** A blank line or a `#` comment, skipped wherever actions are read as text. */
export function isSkippable(line: string): boolean {
  const t = line.trim();
  return t === "" || t.startsWith("#");
}

function finiteNumber(field: string, name: string): number {
  const value = Number(field);
  if (field === "" || !Number.isFinite(value)) {
    throw new RunnerError(`${name} must be a number, and "${field}" is not one`);
  }
  return value;
}

/** A commitment named on a line of text (#464): its id, `=`, and the MW.
 * The id `supply` names the fuel supply instead (#469). */
const COMMIT_WORD = /^([a-z][a-z0-9_]*)=(.*)$/;
const SUPPLY_ID = /^[a-z][a-z0-9_]*$/;

/**
 * One turn's action from a line of text: curtailment MW, battery MW (positive
 * discharges, negative charges) and gas MW, separated by spaces or commas.
 * After them may come one word, `accept` or `decline`, answering an open
 * offer, any commitments named as `id=MW`, such as `gas=54`, and on turn 0
 * the fuel supply as `supply=id`, such as `supply=firm`. Leaving the answer
 * out sends none, which the engine treats as a decline, exactly as the venue
 * does.
 */
export function parseActionLine(line: string): Action {
  const fields = line.trim().split(/[\s,]+/).filter((f) => f !== "");
  if (fields.length < 3) {
    throw new RunnerError(
      `expected three numbers (curtail MW, battery MW, gas MW), then optionally accept or decline, commitments such as gas=54 and a supply such as supply=firm, and got "${line.trim()}"`,
    );
  }
  const action: Action = {
    curtail_mw: finiteNumber(fields[0]!, "curtail MW"),
    battery_mw: finiteNumber(fields[1]!, "battery MW"),
    diesel_mw: finiteNumber(fields[2]!, "gas MW"),
  };
  for (const word of fields.slice(3)) {
    const named = COMMIT_WORD.exec(word);
    if (named && named[1] === "supply") {
      if (action.supply !== undefined) throw new RunnerError("the supply is named twice");
      if (!SUPPLY_ID.test(named[2]!)) throw new RunnerError(`"${named[2]}" is not a supply option's id`);
      action.supply = named[2]!;
      continue;
    }
    if (named) {
      const id = named[1]!;
      if (action.commit && id in action.commit) throw new RunnerError(`the ${id} commitment is named twice`);
      action.commit = { ...action.commit, [id]: finiteNumber(named[2]!, `the ${id} commitment`) };
      continue;
    }
    if (action.accept_offer !== undefined) throw new RunnerError(`an offer is answered twice, by "${word}"`);
    const answer = word.toLowerCase();
    if (ACCEPT.has(answer)) action.accept_offer = true;
    else if (DECLINE.has(answer)) action.accept_offer = false;
    else throw new RunnerError(`"${word}" is neither accept, decline, nor a commitment such as gas=54`);
  }
  return action;
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** An action object from JSON, held to the venue's own check: three numbers,
 * accept_offer a boolean when present, commit, when present, a number of MW
 * for each commitment it names (#464), and supply, when present, a string
 * (#469). */
function actionFromJson(value: unknown, where: string): Action {
  if (!isRecord(value)) throw new RunnerError(`${where} is not an action object`);
  const { curtail_mw, battery_mw, diesel_mw, accept_offer, commit, supply } = value;
  for (const [name, v] of [
    ["curtail_mw", curtail_mw],
    ["battery_mw", battery_mw],
    ["diesel_mw", diesel_mw],
  ] as const) {
    if (typeof v !== "number" || !Number.isFinite(v)) {
      throw new RunnerError(`${where}: ${name} must be a number`);
    }
  }
  const action: Action = {
    curtail_mw: curtail_mw as number,
    battery_mw: battery_mw as number,
    diesel_mw: diesel_mw as number,
  };
  if (accept_offer !== undefined) {
    if (typeof accept_offer !== "boolean") throw new RunnerError(`${where}: accept_offer must be true or false`);
    action.accept_offer = accept_offer;
  }
  if (commit !== undefined) {
    if (!isRecord(commit)) throw new RunnerError(`${where}: commit must map commitment ids to MW`);
    for (const [id, mw] of Object.entries(commit)) {
      if (typeof mw !== "number" || !Number.isFinite(mw)) throw new RunnerError(`${where}: commit.${id} must be a number`);
    }
    action.commit = { ...(commit as Record<string, number>) };
  }
  if (supply !== undefined) {
    if (typeof supply !== "string") throw new RunnerError(`${where}: supply must be a supply option's id`);
    action.supply = supply;
  }
  return action;
}

/** Refuse actions recorded against a different pack: same pack is half the
 * promise of "same pack, same actions, same score". */
function samePack(doc: Record<string, unknown>, pack: ScenarioPack, source: string): void {
  if (doc.scenario_id !== undefined && doc.scenario_id !== pack.scenario_id) {
    throw new RunnerError(
      `${source} holds actions for ${JSON.stringify(doc.scenario_id)}, and this pack is ${pack.scenario_id}`,
    );
  }
  if (doc.pack_version !== undefined && doc.pack_version !== pack.pack_version) {
    throw new RunnerError(
      `${source} was recorded against ${pack.scenario_id} pack ${JSON.stringify(doc.pack_version)}, and this pack is ${pack.pack_version}`,
    );
  }
}

function actionsFromJson(doc: unknown, pack: ScenarioPack, source: string): Action[] {
  if (Array.isArray(doc)) return doc.map((a, i) => actionFromJson(a, `${source} action ${i}`));
  if (isRecord(doc) && Array.isArray(doc.line)) {
    // A certified plan from data-g/plans/: the optimizer's line.
    samePack(doc, pack, source);
    return doc.line.map((a, i) => actionFromJson(a, `${source} line ${i}`));
  }
  if (isRecord(doc) && Array.isArray(doc.turns)) {
    // An episode log, from the venue's download or from this runner.
    samePack(doc, pack, source);
    return doc.turns.map((t, i) =>
      actionFromJson(isRecord(t) ? t.action : undefined, `${source} turn ${i}`),
    );
  }
  throw new RunnerError(
    `${source} is JSON but not actions: expected a list of actions, a certified plan with a "line", or an episode log with "turns"`,
  );
}

/**
 * A whole episode's actions from a file's text. JSON may be a list of action
 * objects, a certified plan (`line`), or an episode log (`turns`). Anything
 * else is read as text, one action per line in parseActionLine's form, with
 * blank lines and `#` comments skipped. There must be exactly one action per
 * turn: a short file would leave the day unplayed and a long one would hide a
 * mistake.
 */
export function parseActions(text: string, pack: ScenarioPack, source: string): Action[] {
  const trimmed = text.trim();
  let actions: Action[];
  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    let doc: unknown;
    try {
      doc = JSON.parse(trimmed) as unknown;
    } catch (e) {
      throw new RunnerError(`${source} is not valid JSON: ${(e as Error).message}`);
    }
    actions = actionsFromJson(doc, pack, source);
  } else {
    actions = [];
    text.split(/\r?\n/).forEach((line, i) => {
      if (isSkippable(line)) return;
      try {
        actions.push(parseActionLine(line));
      } catch (e) {
        if (e instanceof RunnerError) throw new RunnerError(`${source} line ${i + 1}: ${e.message}`);
        throw e;
      }
    });
  }
  if (actions.length !== pack.turns) {
    throw new RunnerError(
      `${source} holds ${actions.length} actions, and ${pack.scenario_id} has ${pack.turns} turns`,
    );
  }
  return actions;
}

// -- reading a pack -----------------------------------------------------------------

const isNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/**
 * A pack from a file's text, checked only as far as the engine needs to run
 * it: the fields it reads exist and every per-turn series covers every turn.
 * This is not the acceptance gate. tools/verify_pack.py is, and a pack that
 * plays here can still fail it.
 */
export function parsePack(text: string, source: string): ScenarioPack {
  let doc: unknown;
  try {
    doc = JSON.parse(text) as unknown;
  } catch (e) {
    throw new RunnerError(`${source} is not valid JSON: ${(e as Error).message}`);
  }
  const problems: string[] = [];
  const need = (ok: boolean, what: string) => {
    if (!ok) problems.push(what);
  };
  if (!isRecord(doc)) throw new RunnerError(`${source} is not a scenario pack: it is not a JSON object`);

  need(typeof doc.scenario_id === "string", "scenario_id is missing");
  need(typeof doc.pack_version === "string", "pack_version is missing");
  need(typeof doc.title === "string", "title is missing");
  const turns = doc.turns;
  need(Number.isInteger(turns) && (turns as number) > 0, "turns must be a whole number above 0");
  need(isNumber(doc.step_minutes) && doc.step_minutes > 0, "step_minutes must be a number above 0");
  need(isNumber(doc.start_hour_local), "start_hour_local is missing");
  need(Array.isArray(doc.events), "events must be a list");

  const series = (v: unknown, name: string, required: boolean) => {
    if (v === undefined && !required) return;
    need(
      Array.isArray(v) && v.length === turns,
      `${name} must hold one value per turn (${String(turns)})`,
    );
  };

  const site = isRecord(doc.site) ? doc.site : null;
  need(site !== null, "site is missing");
  if (site) {
    series(site.it_load_mw, "site.it_load_mw", true);
    need(isNumber(site.sla_usd_per_mwh_shed), "site.sla_usd_per_mwh_shed is missing");
    const battery = isRecord(site.battery) ? site.battery : {};
    for (const k of ["power_mw", "energy_mwh", "efficiency_rt", "initial_soc"]) {
      need(isNumber(battery[k]), `site.battery.${k} is missing`);
    }
    const diesel = isRecord(site.diesel) ? site.diesel : {};
    for (const k of ["power_mw", "permit_hours_remaining", "fuel_usd_per_mwh"]) {
      need(isNumber(diesel[k]), `site.diesel.${k} is missing`);
    }
    series(diesel.fuel_usd_per_mwh_series, "site.diesel.fuel_usd_per_mwh_series", false);
    if (Array.isArray(diesel.supply_options)) {
      diesel.supply_options.forEach((o, i) => {
        const option = isRecord(o) ? o : {};
        need(typeof option.id === "string", `site.diesel.supply_options[${i}].id is missing`);
        need(isNumber(option.premium_usd_per_turn), `site.diesel.supply_options[${i}].premium_usd_per_turn is missing`);
        series(option.available_mw, `site.diesel.supply_options[${i}].available_mw`, true);
      });
    }
  }

  const grid = isRecord(doc.grid) ? doc.grid : null;
  need(grid !== null, "grid is missing");
  if (grid) {
    series(grid.price_usd_per_mwh, "grid.price_usd_per_mwh", true);
    series(grid.system_status, "grid.system_status", true);
    series(grid.price_slope_usd_per_mwh_per_mw, "grid.price_slope_usd_per_mwh_per_mw", false);
    series(grid.import_limit_mw, "grid.import_limit_mw", false);
    if (isRecord(grid.status_response)) {
      series(grid.status_response.system_load_mw, "grid.status_response.system_load_mw", true);
    }
  }

  const scoring = isRecord(doc.scoring) ? doc.scoring : null;
  need(scoring !== null, "scoring is missing");
  if (scoring) {
    need(typeof scoring.score_version === "string", "scoring.score_version is missing");
    need(isNumber(scoring.baseline_cost_usd), "scoring.baseline_cost_usd is missing");
  }

  if (problems.length > 0) {
    throw new RunnerError(
      `${source} is not a playable scenario pack: ${problems.join("; ")}. tools/verify_pack.py runs the full acceptance gate.`,
    );
  }
  return doc as unknown as ScenarioPack;
}
