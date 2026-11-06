# Prompt: author a plausible day by hand

Paste everything under the line into your coding agent's session, after it has read the context
bundle in `kit/README.md`. Replace each bracketed part first.

---

You are building a Palaestra scenario pack in this Exedra repository, with numbers you write
yourself around one tension. Read `CLAUDE.md` and every file in the context bundle in
`kit/README.md` before you write anything. Never edit a file listed in `GENERATED.json`.

**The tension:** [the two outcomes the day should set against each other, such as a cheap night
against a costly relief order]. **What it should probe:** [the obligation two operators would read
differently, or the rule with a perverse outcome, in a sentence].
**The id:** [your C-nnn id]. **The authors:** [each name and affiliation]. **The cohort:** [the
workshop or course, or open submission].

Work in this order.

1. Start from a copy of `docs/contributing/example/c-001.pack.json`. Keep its shape and replace its
   numbers.
2. Design the turn where the player must commit before the information arrives. Build the prices,
   the load and the events around that turn, so the cheapest play and the most reliable play
   differ.
3. Keep hourly turns (`step_minutes: 60`), the only kind the exact optimizer certifies, and one
   value per turn in every series. Keep appeal and order windows from overlapping.
4. Write `provenance`: the authors, the cohort, the source as hand-authored with no external
   dataset, and the license as CC0. Say in `provenance.notes` that the numbers are invented and
   what real situation they imitate.
5. Set `scoring.baseline_cost_usd` to the do-nothing cost: the sum over the turns of
   `site.it_load_mw` times `grid.price_usd_per_mwh` times the turn's length in hours. Every score
   is a fraction of it, so the gate plays the day through the engine with every control left at
   zero and rejects the pack if that costs a cent more or less. Leave `optimal_cost_usd` out
   unless you solved the day yourself: the gate discards it either way.
6. Write a working `brief_md` now, because the gate needs one. It says what the operator in that
   seat would know that morning, from what the board shows, its forecast window included, and
   nothing the day is meant to reveal.
7. Run `poetry run python tools/verify_pack.py <your pack> --certified-out <name>.certified.pack.json --plan-out <name>.plan.json`
   and read every line. Both files are written beside your pack. Fix what a rejection names and
   run it again. A FAIL on the submitted claim does not block acceptance: report the gate's figure
   and the difference. `GATE NOT RUN` is no verdict on the pack: install what it names, then run
   the gate again.
8. Play the certified line with `node web/runner/play.ts <name>.certified.pack.json --actions <name>.plan.json`,
   then play the day yourself. Each turn takes one line: curtailment MW, battery MW and gas MW,
   with `accept` added to take an appeal that is open, as `0 64 0 accept`. Without a terminal,
   write one line per turn into a text file and pass it with `--actions`. Say whether the day
   asked the player to decide anything.
9. Rewrite `brief_md` from what playing taught you, then run the gate once more on the final file.

Hand back the pack file and a paragraph about the day. The paragraph names the seat, the tension,
the control points, what the day teaches and what it probes.
Include the gate's verdict exactly as it printed.
Never present an invented number as a measured one.
