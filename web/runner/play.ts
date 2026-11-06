/**
 * The local runner (#328): play a scenario pack from disk with no database, no
 * account, no secrets and no network. The episode lives in memory and the
 * engine is the venue's own (../shared/engine.ts), so a day played here scores
 * exactly as the same actions score at the venue.
 *
 * Node 22.18 or later runs this file directly, with nothing to install. From
 * web/:
 *
 *   node runner/play.ts ../data-g/packs/s-03.pack.json
 *
 * Each turn prints the board and reads one line: curtailment MW, battery MW
 * (positive discharges, negative charges) and gas MW, with `accept` added to
 * take an open offer, `id=MW` (such as `gas=54`) to name a commitment on the
 * turn it is set, and on turn 0 `supply=id` (such as `supply=firm`) to choose
 * the fuel supply. `quit` abandons the day.
 *
 * Without a terminal (SSH scripts, CI), the same lines are read from standard
 * input, and a bad line or a short supply stops the run with a non-zero exit:
 *
 *   node runner/play.ts <pack> < actions.txt
 *   node runner/play.ts <pack> --actions ../data-g/plans/s-03.plan.json
 *   node runner/play.ts <pack> --actions <file> --log -
 *
 * --actions reads a whole day from a file: text lines, a JSON list of actions,
 * a certified plan, or an episode log downloaded from the venue. --log writes
 * the settled episode's log as JSON to a file, or to standard output when the
 * path is `-`, in which case the turn-by-turn text goes to standard error.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { createInterface } from "node:readline";

import {
  ENGINE_VERSION,
  localTime,
  orderInForce,
  toleranceAt,
  type Action,
  type Observation,
  type Resolution,
} from "../shared/engine.ts";
import type { Commitment, PackEvent, ScenarioPack, SupplyOption } from "../shared/pack.ts";
import type { Star } from "../shared/scoring.ts";
import {
  LocalEpisode,
  RunnerError,
  isSkippable,
  parseActionLine,
  parseActions,
  parsePack,
  type Settlement,
} from "./episode.ts";
import { availability } from "../shared/supply.ts";

/** The part of Node's `process` this file touches, typed here rather than
 * admitting all of @types/node into the program (see tests/node-shims.d.ts). */
interface Writable {
  write(text: string): boolean;
}
interface CliProcess {
  argv: string[];
  exitCode: number | undefined;
  stdin: { isTTY?: boolean };
  stdout: Writable;
  stderr: Writable;
}
const proc = (globalThis as unknown as { process: CliProcess }).process;

function readText(path: string): string {
  try {
    return readFileSync(path, "utf8");
  } catch (e) {
    throw new RunnerError(`cannot read ${path}: ${(e as Error).message}`);
  }
}

const USAGE = `Usage: node runner/play.ts <pack.json> [--actions <file>] [--log <file>|-]

Plays a scenario pack in memory against the venue's engine and scoring.

  <pack.json>        the scenario pack to play
  --actions <file>   play a whole day from a file instead of reading each turn:
                     text lines, a JSON list of actions, a certified plan
                     (data-g/plans/), or an episode log
  --log <file>       write the settled episode's log as JSON; "-" writes it to
                     standard output and moves the turn-by-turn text to
                     standard error
  -h, --help         print this and exit

Each turn's action is one line: curtail MW, battery MW, gas MW, then accept to
take an open offer. Battery MW is positive to discharge and negative to charge.
Example: 0 -100 0     or     0 64 0 accept
At a terminal, quit stops the day. Node 22.18 or later runs this file directly.
`;

class UsageError extends Error {}

interface Args {
  pack: string;
  actions?: string;
  log?: string;
  help: boolean;
}

function parseArgs(argv: string[]): Args {
  const positional: string[] = [];
  const args: Partial<Args> & { help: boolean } = { help: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a === "-h" || a === "--help") args.help = true;
    else if (a === "--actions" || a === "--log") {
      const value = argv[++i];
      if (value === undefined) throw new UsageError(`${a} needs a value`);
      if (a === "--actions") args.actions = value;
      else args.log = value;
    } else if (a.startsWith("--")) throw new UsageError(`unknown option ${a}`);
    else positional.push(a);
  }
  if (args.help) return { pack: "", help: true };
  if (positional.length !== 1) throw new UsageError("name exactly one scenario pack to play");
  return { ...args, pack: positional[0]! };
}

// -- what the player reads ------------------------------------------------------

const round2 = (x: number) => Math.round(x * 100) / 100 + 0; // + 0 turns -0 into 0
const num = (x: number, digits = 2) =>
  round2(x).toLocaleString("en-US", { maximumFractionDigits: digits });
const usd = (x: number) => {
  const s = Math.abs(round2(x)).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return round2(x) < 0 ? `-$${s}` : `$${s}`;
};
/** Markdown as terminal text: bold marks and heading marks dropped. */
const unmark = (md: string) => md.replaceAll("**", "").replace(/^#+\s*/gm, "").trim();
/** The same, folded onto one line for an event notice or a coach line. */
const plain = (md: string) => unmark(md).replace(/\s+/g, " ");

const EVENT_NAMES: Record<PackEvent["type"], string> = {
  conservation_appeal: "Conservation appeal",
  curtailment_order: "Curtailment order",
  absorption_appeal: "Absorption appeal",
  notice: "Notice",
  flow_order: "Operational flow order",
  emergency_order: "Emergency order",
};

/** The two appeals are the offers; an order, a flow order and a notice are not (#635). */
const isOffer = (ev: PackEvent) => ev.type === "conservation_appeal" || ev.type === "absorption_appeal";

function offerOpen(obs: Observation): boolean {
  return obs.events.some((ev) => isOffer(ev) && ev.turns_active.includes(obs.turn));
}

function describeEvent(pack: ScenarioPack, ev: PackEvent, turn: number): string {
  const first = Math.min(...ev.turns_active);
  const last = Math.max(...ev.turns_active);
  const window = `${localTime(pack, first)} to ${localTime(pack, last + 1)}`;
  const terms =
    ev.type === "curtailment_order"
      ? `${num(ev.mw_requested)} MW of relief, ${window}`
      : ev.type === "flow_order"
        ? `${num(ev.tolerance_mw)} MW tolerance on ${ev.commitment}, ${window}`
        : ev.type === "notice"
          ? window
          : ev.type === "emergency_order"
            ? `the gas permit lifted${ev.condition === "last_resort" ? " in emergency hours" : ""}, ${window}`
            : `${usd(ev.credit_usd_per_mwh)}/MWh, ${window}`;
  const now = ev.turns_active.includes(turn);
  const when = now
    ? isOffer(ev)
      ? "open now: add accept to take it"
      : ev.type === "notice"
        ? "now"
        : "in effect now"
    : `starts ${localTime(pack, first)}`;
  // The terms always print: the engine settles by them, and a notice that does
  // not restate them would otherwise hide them (#661). The notice goes below,
  // as a commitment's does.
  const line = `  event  ${EVENT_NAMES[ev.type]}: ${terms}. (${when})`;
  return ev.notice_md ? `${line}\n         ${plain(ev.notice_md)}` : line;
}

/** A commitment's terms and where it stands (#464). Its notice is printed on
 * the turn it is set, which is the turn it matters. */
function describeCommitment(pack: ScenarioPack, c: Commitment, obs: Observation): string {
  const window = `${localTime(pack, c.window[0]!)} to ${localTime(pack, c.window[c.window.length - 1]! + 1)}`;
  const terms =
    c.kind === "nomination"
      ? c.caps_gas
        ? `flat gas MW, ${window}, all the gas there is: output up to it plus the tolerance, ${usd(c.imbalance_usd_per_mwh ?? 0)}/MWh for output below the tolerance`
        : `flat gas MW, ${window}, ${usd(c.imbalance_usd_per_mwh ?? 0)}/MWh for output outside the tolerance`
      : `MW of relief, ${window}, paid ${usd(c.capacity_usd_per_mw ?? 0)}/MW at once, ${usd(c.nonperformance_usd_per_mwh ?? 0)}/MWh for relief below it under an order`;
  const named = obs.commitments?.[c.id];
  const open = obs.turn === c.decision_turn;
  // Under a cap (#635) the most gas this hour is the nomination plus this
  // hour's tolerance, which a flow order in force may have cut.
  const tol = toleranceAt(c, obs.turn, obs.events);
  const capped = c.caps_gas && c.window.includes(obs.turn);
  const state = open
    ? `set it now: add ${c.id}=MW, 0 to ${num(c.max_mw)}`
    : named == null
      ? `set at ${localTime(pack, c.decision_turn)}`
      : capped
        ? `committed ${num(named)} MW; at most ${num(named + tol)} MW of gas this hour, tolerance ${num(tol)} MW`
        : `committed ${num(named)} MW`;
  const lines = [`  commit ${c.label}: ${terms} (${state})`];
  if (open && c.notice_md) lines.push(`         ${plain(c.notice_md)}`);
  return lines.join("\n");
}

/** The fuel supply (#469): every option's terms on turn 0, then the choice
 * and what it delivers this hour. */
function describeSupply(pack: ScenarioPack, options: SupplyOption[], obs: Observation): string {
  const chosen = options.find((o) => o.id === obs.supply);
  if (chosen) {
    return `  supply ${chosen.label}: ${num(obs.site.gas_available_mw ?? 0)} MW of gas this hour, ${usd(chosen.premium_usd_per_turn)} every turn`;
  }
  // The play screen's words for the same terms (shared/supply.ts), with the
  // day named when the episode runs past one.
  const multiDay = pack.turns * pack.step_minutes > 24 * 60;
  const at = (t: number) =>
    multiDay
      ? `day ${Math.floor((pack.start_hour_local * 60 + t * pack.step_minutes) / (24 * 60)) + 1}, ${localTime(pack, t)}`
      : localTime(pack, t);
  const lines = [`  supply choose one now: add supply=id (the first is taken if you name none)`];
  for (const o of options) {
    lines.push(
      `         ${o.id}: ${o.label}, ${usd(o.premium_usd_per_turn)} every turn, ${availability(o, pack.site.diesel.power_mw, at)}`,
    );
  }
  return lines.join("\n");
}

function describeOpening(pack: ScenarioPack): string {
  const opt = pack.scoring.optimal_cost_usd;
  return [
    `${pack.scenario_id} ${pack.title}`,
    `pack ${pack.pack_version} · ${pack.turns} turns of ${pack.step_minutes} minutes from ${localTime(pack, 0)}`,
    `baseline ${usd(pack.scoring.baseline_cost_usd)} · ${opt === undefined ? "no certified optimum, so no stars" : `certified optimum ${usd(opt)}`}`,
    "",
    unmark(pack.brief_md),
    "",
  ].join("\n");
}

function describeObservation(pack: ScenarioPack, obs: Observation): string {
  const lines = [
    `Turn ${obs.turn + 1} / ${pack.turns} · ${obs.local_time}`,
    `  grid   ${usd(obs.price_usd_per_mwh)}/MWh · ${obs.system_status}`,
  ];
  if (obs.forecast.length > 0) {
    const next = obs.forecast.map(
      (f, i) =>
        `${localTime(pack, obs.turn + 1 + i)} ${usd(f.price_usd_per_mwh)} ${f.system_status}`,
    );
    lines.push(`  ahead  ${next.join(" · ")}`);
  }
  const b = pack.site.battery;
  // An emergency order in force (#465) lifts the permit for the hour.
  const waived = orderInForce(obs.events, obs.system_status, obs.turn)
    ? " (the emergency order covers this hour)"
    : "";
  lines.push(
    `  site   IT ${num(obs.site.it_demand_mw)} MW · battery ${num(obs.site.battery_soc_mwh)} of ${num(b.energy_mwh)} MWh (${num(b.power_mw)} MW) · gas ${num(pack.site.diesel.power_mw)} MW, ${obs.site.diesel_permit_hours} permit hours left${waived}`,
  );
  if (obs.site.stocks) {
    const units = new Map((pack.site.stocks ?? []).map((s) => [s.id, s]));
    const held = Object.entries(obs.site.stocks).map(([id, level]) => {
      const s = units.get(id);
      return s ? `${s.label} ${num(level)} of ${num(s.capacity)} ${s.unit}` : `${id} ${num(level)}`;
    });
    lines.push(`  stocks ${held.join(" · ")}`);
  }
  if (obs.site.fuel_usd_per_mwh !== undefined) {
    const ahead = obs.forecast.map((f) => usd(f.fuel_usd_per_mwh ?? 0));
    lines.push(`  fuel   ${usd(obs.site.fuel_usd_per_mwh)}/MWh now${ahead.length > 0 ? `, then ${ahead.join(" · ")}` : ""}`);
  }
  const options = pack.site.diesel.supply_options;
  if (options) lines.push(describeSupply(pack, options, obs));
  for (const c of pack.commitments ?? []) lines.push(describeCommitment(pack, c, obs));
  for (const ev of obs.events) lines.push(describeEvent(pack, ev, obs.turn));
  const l = obs.ledger;
  const underOrder =
    l.order_hours_used !== undefined ? ` · ${l.order_hours_used} gas hours under the emergency order` : "";
  lines.push(
    `  ledger cost ${usd(l.cost_usd)} · shed ${num(l.sla_shed_mwh)} MWh · relief ${num(l.reliability_delivered_mwh)} of ${num(l.reliability_asked_mwh)} MWh asked${underOrder}`,
  );
  const coach = pack.coach_md?.[obs.turn];
  if (coach) lines.push(`  coach  ${plain(coach)}`);
  return lines.join("\n");
}

function describeResolution(r: Resolution): string {
  const a = r.applied;
  const battery =
    a.battery_mw > 0 ? `discharge ${num(a.battery_mw)}` : a.battery_mw < 0 ? `charge ${num(-a.battery_mw)}` : "idle";
  const committed = Object.entries(a.commit ?? {}).map(([id, mw]) => ` · committed ${id} ${num(mw)} MW`);
  const supplied = a.supply !== undefined ? ` · supply ${a.supply}` : "";
  const lines = [
    `  played curtail ${num(a.curtail_mw)} MW · battery ${battery}${a.battery_mw === 0 ? "" : " MW"} · gas ${num(a.diesel_mw)} MW${a.accept_offer ? " · offer accepted" : ""}${committed.join("")}${supplied}`,
  ];
  for (const note of r.clamp_notes) lines.push(`  clamp  ${note}`);
  // A positive settlement is a charge and a negative one a payment, already in the turn cost.
  const settled = r.commitment_usd ? ` · commitments ${usd(r.commitment_usd)}` : "";
  const premium = r.supply_usd ? ` · supply ${usd(r.supply_usd)}` : "";
  lines.push(
    `  result grid import ${num(r.grid_import_mw)} MW at ${usd(r.effective_price_usd_per_mwh)}/MWh · turn cost ${usd(r.turn_cost_usd)} · credit ${usd(r.credit_usd)} · relief ${num(r.delivered_relief_mw)} MW${settled}${premium}`,
  );
  return lines.join("\n") + "\n";
}

const STAR_NAMES: Record<Star, string> = {
  ribbon: "Blue Ribbon (the certified optimum, to the penny)",
  gold: "gold (within 1% of the optimum)",
  silver: "silver (within 2%)",
  bronze: "bronze (within 3%)",
};

function describeSettlement(pack: ScenarioPack, s: Settlement): string {
  const { cost, reliability } = s.score;
  const opt = pack.scoring.optimal_cost_usd;
  const star =
    opt === undefined
      ? "this pack has no certified optimum, so it awards no stars"
      : s.star
        ? `star ${STAR_NAMES[s.star]}`
        : "no star: a star needs full relief and a cost within 3% of the optimum";
  return [
    "Settled.",
    `  cost        ${usd(cost.value_usd)} against a do-nothing baseline of ${usd(cost.baseline_usd)} (${cost.vs_baseline.toFixed(4)} of baseline)`,
    `  reliability ${num(reliability.delivered_mwh)} of ${num(reliability.asked_mwh)} MWh asked delivered (${reliability.ratio.toFixed(4)})`,
    // The emergency order's ledger (#465): never in the cost.
    ...(s.final.order_hours_used !== undefined
      ? [`  exposure    ${s.final.order_hours_used} gas hours run under the emergency order, logged as emissions exposure`]
      : []),
    `  ${star}${opt === undefined ? "" : `; certified optimum ${usd(opt)}`}`,
    `  scoring ${s.score.score_version} · engine ${ENGINE_VERSION}`,
    "",
  ].join("\n");
}

function prompt(obs: Observation): string {
  return offerOpen(obs) ? "action (curtail battery gas [accept])> " : "action (curtail battery gas)> ";
}

// -- where actions come from --------------------------------------------------------

interface ActionSource {
  /** The next turn's action, or null when the player stops or input runs out. */
  next(obs: Observation): Promise<Action | null>;
  close(): void;
}

function scriptedSource(actions: Action[], out: Writable): ActionSource {
  let i = 0;
  return {
    next(obs) {
      const a = actions[i++] ?? null;
      if (a) out.write(`${prompt(obs)}${a.curtail_mw} ${a.battery_mw} ${a.diesel_mw}${a.accept_offer === undefined ? "" : a.accept_offer ? " accept" : " decline"}\n`);
      return Promise.resolve(a);
    },
    close() {},
  };
}

/** Lines from standard input. At a terminal a bad line is explained and asked
 * again; from a pipe it stops the run, naming the line, because nobody is
 * there to retype it. */
function stdinSource(interactive: boolean, out: Writable): ActionSource {
  const rl = createInterface({ input: proc.stdin, terminal: false });
  const lines = rl[Symbol.asyncIterator]();
  let lineNo = 0;
  return {
    async next(obs) {
      out.write(prompt(obs));
      for (;;) {
        const got = await lines.next();
        if (got.done) {
          if (interactive) out.write("\n");
          return null;
        }
        lineNo++;
        const line = got.value;
        if (isSkippable(line)) {
          if (interactive) out.write(prompt(obs));
          continue;
        }
        if (interactive && ["q", "quit", "exit"].includes(line.trim().toLowerCase())) return null;
        if (!interactive) out.write(`${line.trim()}\n`);
        try {
          return parseActionLine(line);
        } catch (e) {
          if (!(e instanceof RunnerError)) throw e;
          if (!interactive) throw new RunnerError(`standard input line ${lineNo}: ${e.message}`);
          out.write(`  ${e.message}\n${prompt(obs)}`);
        }
      }
    },
    close() {
      rl.close();
    },
  };
}

// -- the day ---------------------------------------------------------------------

async function play(args: Args): Promise<number> {
  // With the log on standard output, everything a person reads moves aside.
  const out = args.log === "-" ? proc.stderr : proc.stdout;
  const pack = parsePack(readText(args.pack), args.pack);
  const scripted = args.actions ? parseActions(readText(args.actions), pack, args.actions) : null;
  const interactive = scripted === null && proc.stdin.isTTY === true;
  const episode = new LocalEpisode(pack, {
    player: { id: "local:runner", kind: interactive ? "human" : "agent" },
  });
  const source = scripted ? scriptedSource(scripted, out) : stdinSource(interactive, out);

  out.write(describeOpening(pack) + "\n");
  try {
    while (!episode.over) {
      const obs = episode.observation();
      out.write(describeObservation(pack, obs) + "\n");
      const action = await source.next(obs);
      if (action === null) {
        proc.stderr.write(
          `play: the day stopped at turn ${episode.turn + 1} of ${pack.turns}, so nothing was scored and no log was written\n`,
        );
        return 1;
      }
      const { resolution, settlement } = episode.play(action);
      out.write(describeResolution(resolution));
      if (settlement) out.write("\n" + describeSettlement(pack, settlement));
    }
  } finally {
    source.close();
  }

  if (args.log) {
    const json = JSON.stringify(episode.log, null, 2) + "\n";
    if (args.log === "-") proc.stdout.write(json);
    else {
      writeFileSync(args.log, json);
      out.write(`log written to ${args.log}\n`);
    }
  }
  return 0;
}

async function main(argv: string[]): Promise<number> {
  let args: Args;
  try {
    args = parseArgs(argv);
  } catch (e) {
    if (!(e instanceof UsageError)) throw e;
    proc.stderr.write(`play: ${e.message}\n\n${USAGE}`);
    return 2;
  }
  if (args.help) {
    proc.stdout.write(USAGE);
    return 0;
  }
  try {
    return await play(args);
  } catch (e) {
    const message = e instanceof RunnerError ? e.message : e instanceof Error ? (e.stack ?? e.message) : String(e);
    proc.stderr.write(`play: ${message}\n`);
    return 1;
  }
}

proc.exitCode = await main(proc.argv.slice(2));
