# Prompt: compile a day from public data

Paste everything under the line into your coding agent's session, after it has read the context
bundle in `kit/README.md`. Replace each bracketed part first.

---

You are building a Palaestra scenario pack in this Exedra repository, compiled from a real day in a
public data source. Read `CLAUDE.md` and every file in the context bundle in `kit/README.md` before
you write anything. Never edit a file listed in `GENERATED.json`.

**The day:** [the source, such as the NREL RTS-GMLC testbed, and the date or the event you want].
**The id:** [your C-nnn id]. **The authors:** [each name and affiliation]. **The cohort:** [the
workshop or course, or open submission].
**What it should probe:** [the obligation two operators would read differently, or the rule with a
perverse outcome, in a sentence].

Work in this order.

1. Confirm the source's license permits redistributing a series derived from it, and quote the
   terms with their URL. The gate recognizes the NREL RTS-GMLC testbed and the ENTSO-E
   Transparency Platform's list of data open for re-use under CC-BY 4.0. It also recognizes ERCOT's
   public website, whose terms permit only unmodified redistribution, so an ERCOT pack carries
   derived aggregates and never the raw series. If the source's terms do not permit
   redistribution, stop and tell me. If the terms require their notice in every copy, carry the
   notice in full in `provenance.source_notice`.
2. Choose hourly turns (`step_minutes: 60`), the only kind the exact optimizer certifies. Derive
   one value per turn for `grid.price_usd_per_mwh`, `grid.system_status` and `site.it_load_mw`.
   Write in `provenance.notes` exactly how each series came from the source, so anyone can
   reproduce it.
   - RTS-GMLC's time series hold load, not prices. A price can come from the load by a formula you
     state, as S-03's provenance does, but it then peaks with the load in mid-afternoon. The
     testbed's modelled prices are in its PLEXOS day-ahead solution,
     `FormattedData/PLEXOS/PLEXOS_Solution/DAY_AHEAD Solution Files/allTX/PLEXOS_DA_solution_price.csv`
     (`noTX` holds the same without transmission limits), one column per bus, for 5 to 18 July 2020
     only. Write down which file, which buses and how its timestamps map to turns.
   - No public source models the data center itself, so `site.it_load_mw` follows a rule you
     write down, such as a base load plus a share of the system's load.
3. Size the site's battery and generator to the day, so the player's choices matter. Add a
   conservation appeal or a curtailment order where the source's day had a real notice. A
   synthetic source such as RTS-GMLC has no notices, so there you author the events on a rule
   you state, and `provenance.notes` says they are authored. Never present an authored event as a
   real one. Keep appeal and order windows from overlapping.
4. Set `scenario_id`, `title`, `provenance` and the two metrics as the worked example does. Set
   `scoring.baseline_cost_usd` to the do-nothing cost: the sum over the turns of `site.it_load_mw`
   times `grid.price_usd_per_mwh` times the turn's length in hours. Every score is a fraction of
   it, so the gate plays the day through the engine with every control left at zero and rejects
   the pack if that costs a cent more or less. Leave `optimal_cost_usd` out unless you solved the
   day yourself: the gate discards it either way.
5. Write a working `brief_md` now, because the gate needs one. It says what the operator in that
   seat would know that morning, from what the board shows, its forecast window included, and
   nothing the day is meant to reveal.
6. Run `poetry run python tools/verify_pack.py <your pack> --certified-out <name>.certified.pack.json --plan-out <name>.plan.json`
   and read every line. Both files are written beside your pack. Fix what a rejection names and
   run it again. A FAIL on the submitted claim does not block acceptance: report the gate's figure
   and the difference. `GATE NOT RUN` is no verdict on the pack: install what it names, then run
   the gate again.
7. Play the certified line with `node web/runner/play.ts <name>.certified.pack.json --actions <name>.plan.json`,
   then play the day yourself. Each turn takes one line: curtailment MW, battery MW and gas MW,
   with `accept` added to take an appeal that is open, as `0 64 0 accept`. Without a terminal,
   write one line per turn into a text file and pass it with `--actions`. Say whether the day
   asked the player to decide anything.
8. Rewrite `brief_md` from what playing taught you, then run the gate once more on the final file.

Hand back the pack file and a paragraph about the day. The paragraph names the seat, the tension,
the control points, what the day teaches and what it probes.
Include the gate's verdict exactly as it printed.
Never invent a source, a license or a number presented as measured.
