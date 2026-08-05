# Exedra

**The public workshop for [Palaestra](https://palaestra.thrivetech.ai)
scenarios.** Build a day at the grid interface, play it, verify it, submit it.

## ➜ [Read the wiki](https://github.com/martymcenroe/Exedra/wiki)

The wiki is the documentation. This page is the doorway.

---

## What this is

In a Greek palaestra the *exedra* was the room off the colonnade, fitted with
stone benches, where trainers and philosophers sat and talked with students.
Vitruvius put it in his plan of the building: seats "in which philosophers,
rhetoricians, and others who delight in study may sit and converse."

It is the room you learn in before you go out on the sand.

Palaestra is the court. You run a data center at the grid interface for a
simulated day, and you are scored against a certified optimal line. Exedra is
the room outside it: enough of the platform, in the open, that you can build a
scenario of your own and submit it.

## Where to go

| Page | What it answers |
|---|---|
| [Goals](https://github.com/martymcenroe/Exedra/wiki/Goals) | Why this exists and who it is for |
| [The Venue](https://github.com/martymcenroe/Exedra/wiki/The-Venue) | What Palaestra is, and the thesis underneath it |
| [Where This Is Going](https://github.com/martymcenroe/Exedra/wiki/Where-This-Is-Going) | Committed work, possibilities, and four inventions offered for argument |
| [Architecture](https://github.com/martymcenroe/Exedra/wiki/Architecture) | Three programs, and only one of them runs during a game |
| [The Competitor Contract](https://github.com/martymcenroe/Exedra/wiki/The-Competitor-Contract) | The interface every player and every agent speaks |
| [The Engine](https://github.com/martymcenroe/Exedra/wiki/The-Engine) | The complete rules, and the list of what is not modeled |
| [The Scenario Pack](https://github.com/martymcenroe/Exedra/wiki/The-Scenario-Pack) | The file you are actually writing |
| [Scoring and Stars](https://github.com/martymcenroe/Exedra/wiki/Scoring-and-Stars) | Two metrics, their denominators, and where the maximum comes from |
| [What Exedra Withholds](https://github.com/martymcenroe/Exedra/wiki/What-Exedra-Withholds) | What is deliberately not here, and why |
| [Hydration](https://github.com/martymcenroe/Exedra/wiki/Hydration) | How this repository is generated |

## What you will be able to do here

Clone it. Compile a scenario from public grid data. Play it against the same
engine the venue runs. Check it against the same acceptance gate the venue
uses. Open a pull request.

You need a text editor and public data. You do not need an account, a database,
a cloud provider, or a key.

Two scenarios come with it. **First Shift**, six coached turns on hand-authored
arithmetic. **Curtailment Order**, sixteen hours compiled from the NREL RTS-GMLC
reliability testbed.

## Status

**The wiki is ahead of this repository.** Those pages describe Exedra as
designed. The code arrives by export from the platform, and this table says what
is actually in the tree today.

| Part | State |
|---|---|
| Goals and architecture, on the wiki | Written |
| Engine, scoring, schema | Not yet exported |
| Acceptance gate and optimizer | Not yet exported |
| First Shift and Curtailment Order | Not yet exported |
| Local runner | Not yet built |
| Contribution tutorials and prompts | Not yet written |

If you arrived early and want to help, the wiki is the specification. Read
[Goals](https://github.com/martymcenroe/Exedra/wiki/Goals) first.

## One thing not to do

The engine, the scoring function, the schema, and the gate are copied in from
the platform, so a change to any of them is made upstream rather than here.
[Hydration](https://github.com/martymcenroe/Exedra/wiki/Hydration) explains why,
and what to send instead.

## Licence

PolyForm Noncommercial 1.0.0. See [LICENSE](LICENSE).

---

*Palaestra is live at [palaestra.thrivetech.ai](https://palaestra.thrivetech.ai).
Playing a scenario is the fastest way to understand what you would be building.*
