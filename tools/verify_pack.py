# GENERATED from martymcenroe/Palaestra by tools/export_exedra.py (#323). Do not edit it here: a change made here is overwritten by the next export and fails the drift test. Change it upstream, or open an issue with a scenario pack that shows the problem.

"""Acceptance gate for a contributed scenario pack (#213, design 0007).

One command, one pack, one verdict. The machinery it runs already existed,
scattered across the compiler and a test file and wired to nothing that
takes an arbitrary pack as input: `main()` compiles the five packs we ship
and there was no entry point answering "is this JSON publishable?".

The doctrine it enforces (design 0007): a contributed `optimal_cost_usd` is
NOT checked, it is DISCARDED. The submitted number never reaches a player.
We recompute from the pack alone and replay the recomputed line through the
real engine, and only that number is published. The contributor's claim is
still reported back as a delta, because in a workshop the disagreement
between their solver and ours is the most instructive artifact the exercise
produces: a solver's answer is a hypothesis until the engine confirms it.

Three verdicts:

    accept-with-stars   schema, invariants, the stated baseline, recomputed
                        optimum, engine parity
    accept-unstarred    valid and playable, but no optimum can be certified
                        (price slope present, non-hourly turns, curtailment
                        not priced out, or appeal and order windows overlap).
                        Published honestly, exactly as S-09 is today.
    reject              with the reason, in language a student can act on,
                        among them a stated baseline that is not what doing
                        nothing costs (#665).

The baseline and parity checks run in TypeScript because the engine is the
TypeScript one and a Python reimplementation would defeat the entire point.
Rather than a second replay path, this stages the candidate where
web/tests/baseline.test.ts and web/tests/optimal.test.ts already look and
runs those suites, so a candidate is held to the same rules as the catalogue
by the same code.

Usage:
    poetry run python tools/verify_pack.py path/to/candidate.pack.json
    poetry run python tools/verify_pack.py candidate.json --json
    poetry run python tools/verify_pack.py candidate.json --certified-out load.pack.json
    poetry run python tools/verify_pack.py candidate.json --certified-out load.pack.json --plan-out load.plan.json

`--certified-out` writes, on an accept, the pack a maintainer loads (#642):
the certified optimum in place of the claimed one, or no optimum at all when
the verdict is unstarred. A rejected pack writes nothing. `--plan-out` writes,
on accept-with-stars only, the certified line in the catalogue's plan format,
which `node web/runner/play.ts <pack> --actions <plan>` plays (#663).

When the parity suite cannot run at all (vitest missing, or the suite fails
with no test failed), there is no verdict on the pack: the gate says GATE NOT
RUN, exits 2 and writes nothing (#662).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from jsonschema.exceptions import ValidationError

from palaestra.compiler import (
    compute_optimal_milp,
    optimal_line,
    validate_pack,
    write_plan,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKS_DIR = REPO_ROOT / "data-g" / "packs"
KNOWN_SOURCES = REPO_ROOT / "data-g" / "licensing" / "known-sources.json"
WEB_DIR = REPO_ROOT / "web"
# Under data/ (gitignored, ephemeral) rather than data-g/: a candidate is not
# source of truth, and it must never be mistaken for part of the catalogue.
STAGING = REPO_ROOT / "data" / "verify-candidates"
# vitest's JSON report of an engine suite's run, the baseline suite's or the
# parity suite's, one at a time. Beside STAGING, never in it: every file in
# STAGING is a candidate, and a leftover there stops the next run.
PARITY_REPORT = REPO_ROOT / "data" / "verify-parity-report.json"
# The baseline suite's failure message, web/tests/baseline.test.ts's own
# wording: the two figures a contributor needs, whatever vitest wraps them in.
BASELINE_MISS = re.compile(r"the pack states \$[\d,.]+, doing nothing costs \$[\d,.]+")

ACCEPT_STARS = "accept-with-stars"
ACCEPT_UNSTARRED = "accept-unstarred"
REJECT = "reject"


class Rejected(Exception):
    """A fault the contributor must fix before the pack can be published."""


class GateNotRun(Exception):
    """The gate's own machinery could not run, so there is no verdict on the pack."""


class StagingOccupied(GateNotRun):
    """Files from an earlier run are still staged, so this run cannot stage its own."""


def toolchain_problem() -> str | None:
    """Why the parity suite cannot run on this machine, or None (#662).

    A missing vitest used to read as "the certified optimum did not replay",
    which blamed the pack for the machine.
    """
    if shutil.which("npx") is None:
        return "npx is not on PATH: install Node.js 22.18 or later, then run the gate again"
    if not (WEB_DIR / "node_modules" / "vitest" / "package.json").is_file():
        return (
            "vitest is not installed in web/: from the repository root run "
            "`npm ci --prefix web`, then the gate again"
        )
    return None


def catalogue_ids() -> set[str]:
    return {
        json.loads(p.read_text())["scenario_id"]
        for p in sorted(PACKS_DIR.glob("*.pack.json"))
    }


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Rejected(f"no such file: {path}") from None
    except json.JSONDecodeError as exc:
        raise Rejected(f"not valid JSON: {exc}") from None


def check_shape(pack: dict) -> None:
    """Schema plus the cross-field invariants the schema cannot express."""
    try:
        validate_pack(pack)
    except ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path) or "(root)"
        raise Rejected(f"schema: {where}: {exc.message}") from None
    except ValueError as exc:
        raise Rejected(f"invariant: {exc}") from None


def check_identity(pack: dict) -> None:
    """A contributed scenario must not occupy a catalogue id."""
    sid = pack["scenario_id"]
    if sid in catalogue_ids():
        raise Rejected(
            f"scenario_id {sid} is already published. Contributed scenarios take "
            f"the C-nnn namespace (design 0007) and must never overwrite a "
            f"catalogue entry."
        )


def describe_provenance(pack: dict) -> str:
    """Report the attribution the schema has already enforced (#214).

    For a C-nnn pack the schema requires authors, cohort, source, source_url
    and source_license, so by the time we get here they are present and this
    is a summary rather than a check. Surfacing it matters anyway: named
    authorship is the whole incentive for a student to do the work, and the
    licence attestation is what #217 will later check against a maintained
    list of known-permissive sources.
    """
    prov = pack.get("provenance", {})
    if not pack["scenario_id"].startswith("C-"):
        return "catalogue pack; contributor fields not required"
    authors = prov.get("authors", [])
    names = ", ".join(f"{a['name']} ({a['affiliation']})" for a in authors)
    scope = prov.get("system_load_scope")
    scope_note = (
        ""
        if scope is None
        else f"; load series excludes {scope['excluded'] or 'nothing stated'}"
    )
    return f"{names}; {prov.get('source_license')}{scope_note}"


def licence_standing(pack: dict) -> tuple[bool, str]:
    """Check the attested source against the known-sources list (#217).

    Recognition never rejects: an unrecognized source is surfaced for the
    human key to weigh, because the list is a floor, not a wall. What the
    check ends is the era of the tool taking every licence purely on the
    contributor's word without even looking.
    """
    if not pack["scenario_id"].startswith("C-"):
        return True, "catalogue pack; licence review happened at compile"
    prov = pack.get("provenance", {})
    haystack = f"{prov.get('source_url', '')} {prov.get('source_license', '')}".lower()
    known = json.loads(KNOWN_SOURCES.read_text(encoding="utf-8"))["sources"]
    for src in known:
        if any(tok in haystack for tok in src["match"]):
            # ASCII join: this renders in whatever console a workshop has.
            return True, f"{src['name']}: {src['standing']}. {src['conditions']}"
    return False, (
        "source not on the known list (data-g/licensing/known-sources.json); "
        "the attestation stands on the contributor's word and the signing "
        "human should read the source's terms before accepting"
    )


# The optimizer's assertions are written for whoever is reading the compiler.
# A contributor reading a verdict needs to know what to change, so each known
# refusal is translated. An unmapped one still surfaces verbatim rather than
# being flattened into "something went wrong".
_REFUSALS = {
    "optimizer assumes hourly turns": (
        "the exact optimizer only solves hourly turns, so step_minutes must be 60"
    ),
    "slope-free only": (
        "the pack carries grid.price_slope_usd_per_mwh_per_mw, and the exact "
        "optimizer is slope-free: it cannot certify a day where the player's own "
        "draw moves the price"
    ),
    "curtailment priced out": (
        "site.sla_usd_per_mwh_shed is not above every attainable price plus credit, "
        "so shedding load could be cheaper than serving it and the optimum is not "
        "the fully-delivering play the star ladder assumes"
    ),
    "appeal and order windows overlap": (
        "a conservation appeal and a curtailment order cover the same turn. The "
        "engine pays no voluntary credit under an order (#183); the optimizer "
        "prices them as disjoint, so it would publish a gold line no play can reach"
    ),
}

# A field the optimizers do not model yet (#584). The optimizer's own message
# names the field, so it is kept beside the translation.
_UNMODELED = "optimizer does not model"


def explain_refusal(message: str) -> str:
    for key, text in _REFUSALS.items():
        if key in message:
            return text
    if _UNMODELED in message:
        return (
            "the pack uses a mechanic the exact optimizer does not model yet, so "
            f"no optimum can be certified for it ({message})"
        )
    return message or "the optimizer refused the pack"


def recompute(pack: dict) -> tuple[dict | None, str]:
    """Discard any submitted optimum and solve the pack ourselves.

    Returns (plan, reason). A None plan means no optimum can be certified,
    which is publishable but unstarred rather than a rejection.
    """
    pack["scoring"].pop("optimal_cost_usd", None)
    try:
        return compute_optimal_milp(pack), "certified by exact MILP"
    except AssertionError as exc:
        # The optimizers refuse what they cannot prove. That refusal is the
        # behaviour we want at a contribution boundary, so it is an outcome
        # here rather than a crash.
        return None, explain_refusal(str(exc))


def show_output(output: str) -> None:
    """Print the parity suite's own output on stderr, above the verdict (#662)."""
    sys.stderr.write("---- vitest output ----\n")
    sys.stderr.write(output.rstrip() + "\n")
    sys.stderr.write("---- end of vitest output ----\n")


def read_report() -> dict | None:
    try:
        return json.loads(PARITY_REPORT.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def stage_pack(pack: dict) -> Callable[[Path], None]:
    """Write the candidate pack where an engine suite globs for it."""
    return lambda path: path.write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n")


def run_engine_suite(
    suite: str, staged: dict[Path, Callable[[Path], None]], marker: str, label: str
) -> tuple[bool, str]:
    """Stage the candidate's files and run one of the catalogue's own engine suites.

    `staged` maps each file to write into STAGING to the function that writes
    it; `marker` is the part of the candidate's own test name that proves the
    suite reached it; `label` names the suite in what the gate prints.

    The gate deletes only the files it wrote, each by name (#643). The empty
    directory may stay: the suites glob files in it, never the directory
    itself. Files already there at the start belong to a run that did not
    finish, and the suites would read them as catalogue, so the run refuses
    rather than staging beside them or guessing they can go.

    vitest's JSON report decides the outcome (#662). A failed test is a verdict
    on the pack. A suite that failed with no test failed, wrote no report, or
    never reached the candidate's own test is the machine's fault, and raises
    GateNotRun rather than blaming the pack.
    """
    STAGING.mkdir(parents=True, exist_ok=True)
    leftovers = sorted(p.name for p in STAGING.iterdir())
    if leftovers:
        raise StagingOccupied(
            f"{STAGING} still holds {', '.join(leftovers)} from a run that did not "
            "finish. The engine suites would read them as catalogue. Delete "
            "those files, then run the gate again."
        )
    problem = toolchain_problem()
    if problem:
        raise GateNotRun(problem)
    PARITY_REPORT.unlink(missing_ok=True)  # a stale report must never be read as this run's
    try:
        for path, write in staged.items():
            write(path)
        proc = subprocess.run(  # noqa: S602 — fixed command: the suite name is the gate's own
            f"npx vitest run tests/{suite} --reporter=default --reporter=json "
            f'--outputFile.json="{PARITY_REPORT}"',  # noqa: S607 — npx from PATH is the point
            cwd=WEB_DIR,
            shell=True,
            capture_output=True,
            text=True,
        )
        output = proc.stdout + proc.stderr
        report = read_report()
        if report is None:
            show_output(output)
            raise GateNotRun(
                f"the {label} did not run: vitest wrote no report (its output is above)"
            )
        results = [a for suite in report.get("testResults", []) for a in suite.get("assertionResults", [])]
        if report.get("numFailedTests", 0) > 0:
            show_output(output)
            messages = [m for a in results if a.get("status") == "failed" for m in a.get("failureMessages", [])]
            detail = next(
                (ln.strip() for m in messages for ln in m.splitlines() if "expected" in ln.lower()),
                f"a test in the {label} failed: see the vitest output above",
            )
            return False, detail
        if proc.returncode != 0 or not report.get("success", False):
            show_output(output)
            raise GateNotRun(f"the {label} failed to run with no test failed (its output is above)")
        mine = [a for a in results if marker in a.get("fullName", "")]
        if not mine or any(a.get("status") != "passed" for a in mine):
            show_output(output)
            raise GateNotRun(
                f"the {label} passed without reaching {marker}, "
                "so it proves nothing about this pack"
            )
        return True, ""
    finally:
        for path in [*staged, PARITY_REPORT]:
            path.unlink(missing_ok=True)


def check_baseline(pack: dict) -> str:
    """Hold the stated baseline to the engine's, to the cent (#665).

    `scoring.baseline_cost_usd` is the denominator of every score on the pack,
    so a wrong one makes every score wrong. The engine settles it the way
    web/tests/baseline.test.ts holds the catalogue to it: a player who does
    nothing is charged exactly the stated figure. A miss is the contributor's
    to fix, so it rejects, naming both figures.
    """
    sid = pack["scenario_id"].lower()
    ok, detail = run_engine_suite(
        "baseline.test.ts",
        {STAGING / f"{sid}.pack.json": stage_pack(pack)},
        f"{sid}.pack.json costs its published baseline",
        "baseline suite",
    )
    if not ok:
        found = BASELINE_MISS.search(detail)
        raise Rejected(
            "scoring.baseline_cost_usd is not what doing nothing costs: "
            f"{found.group(0) if found else detail}. Set it to what the engine "
            "charges a player who does nothing: no curtailment, no battery, no "
            "generator, no commitment."
        )
    return f"doing nothing costs the stated ${pack['scoring']['baseline_cost_usd']:,.2f}"


def run_parity(pack: dict, plan: dict) -> tuple[bool, str]:
    """Replay the certified line through the engine with the catalogue's parity suite."""
    sid = pack["scenario_id"].lower()
    ok, detail = run_engine_suite(
        "optimal.test.ts",
        {
            STAGING / f"{sid}.pack.json": stage_pack(pack),
            STAGING / f"{sid}.plan.json": lambda path: write_plan(pack, plan, "milp", path),
        },
        f"{sid}.plan.json replays",
        "engine parity suite",
    )
    return (True, "replayed through the engine to the penny") if ok else (False, detail)


def verify(path: Path) -> dict:
    result: dict = {"pack": str(path), "checks": []}

    def note(name: str, ok: bool, detail: str) -> None:
        result["checks"].append({"check": name, "ok": ok, "detail": detail})

    try:
        pack = load(path)
        check_shape(pack)
        note("schema and invariants", True, "valid")
        check_identity(pack)
        note("scenario id", True, f"{pack['scenario_id']} does not collide")
        note("provenance", True, describe_provenance(pack))
        known, licence_detail = licence_standing(pack)
        note("licence", known, licence_detail)
        note("baseline", True, check_baseline(pack))
    except Rejected as exc:
        result["verdict"] = REJECT
        result["reason"] = str(exc)
        return result

    result["scenario_id"] = pack["scenario_id"]
    result["title"] = pack["title"]
    submitted = pack["scoring"].get("optimal_cost_usd")
    result["submitted_optimal_cost_usd"] = submitted

    plan, reason = recompute(pack)
    if plan is None:
        note("optimum", False, reason)
        result["verdict"] = ACCEPT_UNSTARRED
        result["reason"] = reason
        # recompute() has already discarded the claimed optimum, so this pack
        # awards no stars, which is what the verdict says (#642).
        result["publishable_pack"] = pack
        return result

    certified = plan["cost"]
    pack["scoring"]["optimal_cost_usd"] = certified
    result["certified_optimal_cost_usd"] = certified
    note("optimum", True, f"{reason}: ${certified:,.2f}")

    if submitted is not None:
        delta = submitted - certified
        result["submitted_delta_usd"] = round(delta, 2)
        note(
            "submitted claim",
            abs(delta) < 0.01,
            "agrees with ours"
            if abs(delta) < 0.01
            else f"claimed ${submitted:,.2f}, ours is ${certified:,.2f} "
            f"({delta:+,.2f}). Ours is published; yours is worth investigating.",
        )

    ok, detail = run_parity(pack, plan)
    note("engine parity", ok, detail)
    if not ok:
        result["verdict"] = ACCEPT_UNSTARRED
        result["reason"] = f"the certified optimum did not replay: {detail}"
        # An optimum the engine cannot reach is no gold line (#642).
        pack["scoring"].pop("optimal_cost_usd", None)
        result["publishable_pack"] = pack
        return result

    result["verdict"] = ACCEPT_STARS
    result["line"] = optimal_line(pack, plan)
    result["publishable_pack"] = pack
    result["certified_plan"] = plan
    return result


def write_publishable(pack: dict, out: Path) -> None:
    """The file the venue loads: the gate's certified optimum, never the claimed one (#642)."""
    out.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def render(result: dict) -> None:
    # Deliberately ASCII. This runs in whatever console a workshop participant
    # has, and the compiler's own output already mojibakes its separators on a
    # default Windows code page.
    print(f"pack: {result['pack']}")
    if "scenario_id" in result:
        print(f"      {result['scenario_id']} - {result['title']}")
    print()
    for check in result["checks"]:
        print(f"  {'PASS' if check['ok'] else 'FAIL'}  {check['check']}: {check['detail']}")
    print()
    print(f"VERDICT: {result['verdict']}")
    if "reason" in result:
        print(f"         {result['reason']}")
    if result["verdict"] == ACCEPT_UNSTARRED:
        print("         Playable and publishable. It awards no stars, which is")
        print("         honest rather than a failure: S-09 ships this way.")
    print()
    print("LICENCE CHECK: recognized sources are matched against")
    print("               data-g/licensing/known-sources.json (#217) and their")
    print("               conditions restated above. An unrecognized source is")
    print("               NOT a rejection — it is a flag for the signing human,")
    print("               and the attestation stands on the contributor's word.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pack", type=Path, help="path to the candidate pack JSON")
    ap.add_argument("--json", action="store_true", help="emit the result as JSON")
    ap.add_argument(
        "--certified-out",
        type=Path,
        help="on an accept, write the pack the venue should load: the certified "
        "optimum in place of the claimed one, or no optimum when unstarred",
    )
    ap.add_argument(
        "--plan-out",
        type=Path,
        help="on accept-with-stars, write the certified line as a plan that "
        "`node web/runner/play.ts <pack> --actions <plan>` plays",
    )
    args = ap.parse_args(argv)

    try:
        result = verify(args.pack)
    except GateNotRun as exc:
        # Not a verdict on the pack: the gate could not run, so it says so,
        # writes nothing and exits 2, distinct from a rejection's 1.
        print(f"GATE NOT RUN: {exc}", file=sys.stderr)
        return 2
    publishable = result.pop("publishable_pack", None)
    plan = result.pop("certified_plan", None)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        render(result)
    if args.certified_out is not None:
        if publishable is None:
            print(f"NOT WRITTEN: {args.certified_out}. A rejected pack has nothing to load.",
                  file=sys.stderr)
        else:
            write_publishable(publishable, args.certified_out)
            print(f"WROTE {args.certified_out}: the file to load, never the one handed in.",
                  file=sys.stderr)
    if args.plan_out is not None:
        if plan is None:
            print(f"NOT WRITTEN: {args.plan_out}. Only an accept-with-stars pack has a certified line.",
                  file=sys.stderr)
        else:
            write_plan(publishable, plan, "milp", args.plan_out)
            print(f"WROTE {args.plan_out}: the certified line, for the runner's --actions.",
                  file=sys.stderr)
    return 1 if result["verdict"] == REJECT else 0


if __name__ == "__main__":
    raise SystemExit(main())
