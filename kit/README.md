# The kit: building a scenario with a coding agent

A coding agent can author a scenario pack, but it should not have to reverse-engineer the format
from the schema. This kit is what to put in front of it: the files to read, in order, and a prompt
for the job you want done.

## The context bundle

Point the agent at these files and ask it to read them before it writes anything.

| File | What the agent learns from it |
|---|---|
| `CLAUDE.md` | What this repository is, what it must never edit, and the commands |
| `schema/scenario-pack.v0.schema.json` | The format. It is normative: a field it does not allow is an error |
| `docs/contributing/example/c-001.pack.json` | A complete contributed pack that the gate accepts |
| `data-g/packs/s-03.pack.json` | A pack compiled from public data, with its provenance |
| `web/shared/engine.ts` | The rules the venue resolves each turn by, as code |
| `web/runner/play.ts` | What a player sees each turn, and the one-line action it takes |
| `tools/verify_pack.py` | The acceptance gate: each check it runs and what each verdict means |
| `kit/worth-accepting.md` | What makes a day worth publishing, beyond passing the checks |

The engine's rules are also written out in prose on the wiki, with the list of what the engine
does not model. That list matters most to an agent, which will otherwise model something the
engine ignores. Clone the wiki beside this repository so the agent can read it offline:

```
git clone https://github.com/martymcenroe/Exedra.wiki.git
```

Then add these wiki pages to the bundle: `The-Engine.md`, `The-Scenario-Pack.md` and
`Scoring-and-Stars.md`.

## The two prompts

The two jobs differ, so each has its own prompt.

- [Compile a day from public data](prompt-compile-a-day.md): the agent takes a real day from a
  public source, with a license that permits redistribution, and derives a pack from it.
- [Author a plausible day by hand](prompt-author-a-day.md): the agent writes the numbers itself
  around one tension you name, and the pack is dedicated CC0.

Paste the prompt into the agent's session after the bundle, and fill in the bracketed parts.

## What the agent should hand back

A pack file, the gate's verdict on it as printed, and a paragraph saying what the scenario probes.
An agent that reports success without the gate's printed verdict has not finished.
