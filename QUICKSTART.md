# Quickstart: from clone to a verdict

You copy the worked example, break it on purpose, and watch the acceptance gate refuse it. Then you change one number of your own and watch the gate accept it. The gate here is the gate the venue runs, so a verdict you get here is the verdict the venue gives.

## What you need

- Python 3.12 or later, with [Poetry](https://python-poetry.org/docs/#installation).
- Node.js 22.18 or later. It runs the engine's TypeScript directly, with no build step.

## 1. Clone it

```
git clone https://github.com/martymcenroe/Exedra.git
cd Exedra
poetry install
npm ci --prefix web
```

`poetry install` brings the gate's optimizer and its solver, SciPy. `npm ci --prefix web` brings Vitest, which the gate uses to replay its answer through the engine.

## 2. Play a shipped day

```
node web/runner/play.ts data-g/packs/s-03.pack.json --actions data-g/plans/s-03.plan.json
```

That plays Curtailment Order, a sixteen-hour day compiled from the NREL RTS-GMLC testbed, along its certified optimal line. Its settlement reads:

```
Settled.
  cost        $2,360,524.94 against a do-nothing baseline of $4,533,325.86 (0.5207 of baseline)
  reliability 120 of 120 MWh asked delivered (1.0000)
  star Blue Ribbon (the certified optimum, to the penny); certified optimum $2,360,524.94
```

Leave out `--actions` to play the day yourself. Each turn shows the price, the hours ahead and your site, then asks for one line: curtailment MW, battery MW and gas MW. A positive battery figure discharges and a negative one charges, so `0 -40 0` charges the battery at 40 MW. While an appeal is open, add `accept` to take it, as `0 40 0 accept`. To play without a terminal, write one line per turn into a text file and pass it with `--actions`.

## 3. Copy the worked example

```
cp docs/contributing/example/c-001.pack.json my-day.pack.json
```

`C-001` is a complete pack that the gate accepts. Its day is a six-hour morning on a 90 MW campus with a 40 MW battery, a small gas generator, a paid conservation appeal and a curtailment order. [The Scenario Pack](https://github.com/martymcenroe/Exedra/wiki/The-Scenario-Pack) describes every field.

## 4. Break it on purpose

Open `my-day.pack.json` and change `"turns": 6` to `"turns": 7`. The day now claims seven hours, and it still carries six hours of prices and load.

```
poetry run python tools/verify_pack.py my-day.pack.json
```

The gate refuses it:

```
VERDICT: reject
         invariant: site.it_load_mw: length 6 != turns 7
```

A rejection names the field and the rule it broke. You see a refusal first because a gate that has only ever said yes teaches you nothing about what it checks.

Change `7` back to `6`.

## 5. Make it yours

Change the battery's round-trip efficiency, `"efficiency_rt": 0.9`, to `0.8`. The battery now loses a fifth of what it stores where it lost a tenth.

```
poetry run python tools/verify_pack.py my-day.pack.json --certified-out my-day.certified.pack.json --plan-out my-day.plan.json
```

```
  PASS  schema and invariants: valid
  PASS  scenario id: C-001 does not collide
  PASS  provenance: A. Contributor (Example State University); CC0 (author-created numbers, no external data)
  PASS  licence: hand-authored: permissive. Author-created numbers with no external dataset; CC0 or equivalent dedication stated in provenance.
  PASS  baseline: doing nothing costs the stated $168,300.00
  PASS  optimum: certified by exact MILP: $84,350.00
  FAIL  submitted claim: claimed $61,000.00, ours is $84,350.00 (-23,350.00). Ours is published; yours is worth investigating.
  PASS  engine parity: replayed through the engine to the penny

VERDICT: accept-with-stars
```

The pack is accepted, and the one FAIL line does not block it. The gate discards the optimum a pack claims, solves the day exactly, replays its answer through the engine, and publishes only its own figure. The worked example's author claimed $61,000.00, and their solver had dropped a constraint the engine enforces: the battery starts empty and loses part of every megawatt-hour stored. Finding the constraint a solver dropped is the exercise.

The gate gives one of three verdicts:

- `accept-with-stars`: valid, with a certified optimum the engine reproduces to the penny, so the day awards stars.
- `accept-unstarred`: valid and playable, with no optimum the gate can certify. A price that moves with your own draw is one cause, and turns that are not an hour long are another. The day is published and awards no stars.
- `reject`: the pack cannot be published, and the reason says what to change.

`--certified-out` wrote `my-day.certified.pack.json`, your pack with the gate's optimum in place of the claim. That file is the one the venue would load. `--plan-out` wrote `my-day.plan.json`, the certified line itself, which the gate writes only on `accept-with-stars`.

If the gate prints `GATE NOT RUN`, it could not run its own checks, most often because `npm ci --prefix web` was skipped. That is no verdict on your pack: install what it names and run the gate again.

## 6. Play the day you made

```
node web/runner/play.ts my-day.certified.pack.json --actions my-day.plan.json
```

That plays the certified line, which settles at the gate's optimum and earns the Blue Ribbon. Leave out `--actions` to play the day yourself. Play the certified file so the stars measure you against the line the venue would publish.

## 7. Submit it

A scenario needs an id of its own, and `C-001` belongs to the worked example. Contributed ids run from `C-001` to `C-999`. At a workshop the organizer gives each team one. Otherwise, choose an unused id and say so in your pull request. Then make the pack yours: its `scenario_id`, `title` and `brief_md`, and its `provenance`. The schema requires a contributed pack to name its authors with their affiliations, its cohort, its source, the source's URL and the source's license.

- At a workshop, hand your pack file to the organizer, who runs the gate and loads an accepted pack onto the venue.
- Otherwise, open a pull request that adds your pack under `contributed/`, named for its id in lower case: `contributed/c-101.pack.json` for `C-101`.

A pack can pass every check and still make a dull day. [What makes a scenario worth accepting](kit/worth-accepting.md) says what to aim for, and [the kit](kit/README.md) sets up a coding agent to build one with you.
