# GENERATED from martymcenroe/Palaestra by tools/export_exedra.py (#323). Do not edit it here: a change made here is overwritten by the next export and fails the drift test. Change it upstream, or open an issue with a scenario pack that shows the problem.

"""Scenario pack compiler: RTS-GMLC day-ahead load -> S-03 scenario pack v0.

Tracked in #23. Contract: docs/design/0003-competitor-contract.md.
Schema: schema/scenario-pack.v0.schema.json (validated before writing).

Design stance (vision §5, "believable, not certified"): the compiler is the
only place derivation happens. It picks the annual peak-load day from the
public RTS-GMLC day-ahead regional load series, derives a scarcity price
strip and system-status strip from documented curves, and bakes the S-03
event script and scoring parameters into a self-contained JSON pack. The
runtime engine does deterministic bookkeeping only.

Price model (documented for provenance):
    L = hourly system load / annual peak load        (0..1]
    energy component:  22 + 60 * L^3                 ($/MWh — fuel-stack proxy)
    scarcity adder:    4500 * (L - 0.93) / 0.07      when L > 0.93 (ORDC-style ramp)
Status model:
    emergency if L >= p995 of annual hourly loads, watch if L >= p97,
    else normal; curtailment-order turns are forced to emergency (the order
    IS the emergency, and determinism beats coincidence).

Usage:
    poetry run python -m palaestra.compiler \
        --csv data/rts-gmlc/DAY_AHEAD_regional_Load.csv \
        --out data-g/packs/s-03.pack.json [--fetch]
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import math
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from jsonschema import validate

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_SCHEMA_PATH = REPO_ROOT / "schema" / "scenario-pack.v0.schema.json"

RTS_GMLC_LOAD_URL = (
    "https://raw.githubusercontent.com/GridMod/RTS-GMLC/master/"
    "RTS_Data/timeseries_data_files/Load/DAY_AHEAD_regional_Load.csv"
)

# --- S-03 design parameters (the game design, in one place) -----------------

# 0.3.0 (2026-07-27, #80/#81): natural-gas fuel price recalibrated to
# realistic levels after the natural-gas rename ($320 diesel-era -> $65 S-03,
# $200 -> $120 S-00). Balance change => version bump; leaderboards filter
# by pack_version so earlier-era runs remain visible under their version.
PACK_VERSION = "0.3.0"
SCORE_VERSION = "1.0.0"

# Structured provenance (#325). `source` has always named the dataset in prose;
# these are the fields the acceptance gate actually matches on, via
# data-g/licensing/known-sources.json. Catalogue packs skip that check today,
# so the value here is that S-00 and S-03 are the worked examples every
# contributor copies: a template that omits the fields teaches omitting them.
# Metadata only, so no PACK_VERSION bump — the leaderboards filter on that
# version and a balance-free change must not split them.
RTS_GMLC_URL = "https://github.com/GridMod/RTS-GMLC"
RTS_GMLC_LICENCE = (
    "NREL Data Use Disclaimer Agreement: use, copy and distribute for any "
    "purpose, keeping the notice with all copies; credit DOE, NREL and "
    "ALLIANCE in publications. Series in this pack are DERIVED from the "
    "source, never restated from it."
)
HAND_AUTHORED_LICENCE = (
    "CC0 1.0 Universal public-domain dedication: hand-authored teaching "
    "numbers, no external dataset."
)

TURNS = 16                # 08:00 through 23:00 local, hourly
START_HOUR = 8
FIRST_PERIOD = 9          # RTS Period 9 = hour-ending 09:00 = the 08:00 turn

IT_LOAD_BASE_MW = 280.0   # campus floor load
IT_LOAD_SWING_MW = 20.0   # cooling-driven diurnal swing, follows system shape

SLA_USD_PER_MWH = 6000.0  # value-of-lost-load-scale penalty for shed IT load

BATTERY = {"power_mw": 100.0, "energy_mwh": 400.0, "efficiency_rt": 0.88, "initial_soc": 0.5}
# On-site natural-gas generation. Display name "Natural Gas" (renamed from
# Diesel 2026-07-27, #78); the pack FIELD stays "diesel" as a legacy
# wire identifier — renaming it would break stored episodes and replay.
DIESEL = {"power_mw": 60.0, "permit_hours_remaining": 4, "fuel_usd_per_mwh": 65.0}

APPEAL_CREDIT_USD_PER_MWH = 150.0
ORDER_MW = 40.0
ORDER_HOURS = 3                   # length of the curtailment order window
APPEAL_HOURS = 3                  # voluntary window immediately before the order

STATUS_WATCH_PCTL = 0.97
STATUS_EMERG_PCTL = 0.995

S09_BRIEF_MD = """\
## S-09 · Price-Maker

The same scarcity afternoon you may have survived before, with one rule
changed: **the grid answers back.**

The hourly price you are shown assumes you draw exactly what the campus
needs. Draw less and the price falls. Draw more, including power you pull
in to fill the battery, and it rises. You pay the price you moved.

Your settlement adds a number no other scenario shows, **the neighbors'
bill**: what your operating choices did to the cost of everyone else's
energy.

The forecast here is not an oracle. It assumes the next hours look like
this one. The afternoon disagrees.

No stars on this board. The exact optimum of a price-maker's day is a
harder mathematical object, and this venue does not award unverified gold.
Your measure here is the board, the neighbors, and your own best.
"""

BRIEF_MD = """\
## S-03 · Curtailment Order

You operate a **300 MW-class data-center campus** on a scarcity afternoon.
The system operator will ask for help, first politely, then not.

**Your assets:** the campus IT load itself (shedding it costs SLA money),
a 100 MW / 400 MWh battery, and a 60 MW natural-gas plant with **4 permitted
run-hours** remaining this month.

**You are scored on exactly two numbers, in tension:**

1. **Operating cost.** Energy purchases, fuel, SLA penalties, minus any
   demand-response credits. Reported against the do-nothing baseline.
2. **Reliability contribution.** Of the megawatt-hours a curtailment order
   requires, how many you actually deliver. An appeal's credit counts only in
   the cost.

Every turn is one hour: read the board, set your response, commit. The
scoring function is published and versioned, so you can argue with it
afterward. That argument is the point.
"""


@dataclass
class HourlyLoad:
    year: int
    month: int
    day: int
    period: int  # 1..24, hour-ending
    total_mw: float


def read_load_csv(csv_path: Path) -> list[HourlyLoad]:
    rows: list[HourlyLoad] = []
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        region_cols = [c for c in reader.fieldnames or [] if c not in ("Year", "Month", "Day", "Period")]
        if not region_cols:
            raise ValueError(f"{csv_path}: no region columns found")
        for r in reader:
            rows.append(
                HourlyLoad(
                    year=int(r["Year"]),
                    month=int(r["Month"]),
                    day=int(r["Day"]),
                    period=int(r["Period"]),
                    total_mw=sum(float(r[c]) for c in region_cols),
                )
            )
    if not rows:
        raise ValueError(f"{csv_path}: empty")
    return rows


def find_peak_day(rows: list[HourlyLoad]) -> tuple[int, int, int]:
    peak = max(rows, key=lambda r: r.total_mw)
    return (peak.year, peak.month, peak.day)


def percentile(sorted_vals: list[float], p: float) -> float:
    """Nearest-rank percentile on a pre-sorted list (deterministic, stdlib-only)."""
    if not sorted_vals:
        raise ValueError("empty")
    k = max(0, min(len(sorted_vals) - 1, math.ceil(p * len(sorted_vals)) - 1))
    return sorted_vals[k]


def price_for(load_frac: float) -> float:
    """Documented price curve: fuel-stack proxy + ORDC-style scarcity ramp."""
    price = 22.0 + 60.0 * load_frac**3
    if load_frac > 0.93:
        price += 4500.0 * (load_frac - 0.93) / 0.07
    return round(price, 2)


def price_slope_per_mw(load_frac: float, annual_peak_mw: float) -> float:
    """Grid response (#69): the analytic derivative of price_for with respect
    to one megawatt of campus draw — dP/dMW = dP/dL / peak. On the scarcity
    ramp the cliff term dominates: 4500/(0.07*peak) ~ $7.6/MWh per MW on
    RTS-GMLC, which is why a 100 MW campus is a price-maker at the peak.
    Derived, not invented: same documented curve, one derivative."""
    slope = 180.0 * load_frac**2 / annual_peak_mw
    if load_frac > 0.93:
        slope += 4500.0 / (0.07 * annual_peak_mw)
    return round(slope, 4)


def order_window(loads: list[float]) -> list[int]:
    """The curtailment order lands on the tightest hours of the day: the
    contiguous ORDER_HOURS-long window with the highest summed load. The
    order IS the emergency — placing it anywhere else (e.g. a hardcoded
    evening) breaks the drama when the substrate peaks midday.

    Starts no earlier than turn 2 so there is always room to announce the
    appeal (turn >= 0) and the order (turn >= 1) beforehand.
    """
    if len(loads) < ORDER_HOURS:
        raise ValueError(f"need at least {ORDER_HOURS} turns")
    best_start, best_sum = 2, float("-inf")
    for s in range(2, len(loads) - ORDER_HOURS + 1):
        w = sum(loads[s : s + ORDER_HOURS])
        if w > best_sum:
            best_start, best_sum = s, w
    return list(range(best_start, best_start + ORDER_HOURS))


def appeal_window(order_turns: list[int]) -> list[int]:
    """Voluntary conservation window: the APPEAL_HOURS turns immediately
    before the order, clamped so it never starts before turn 1 (turn 0 is
    for reading the board). This is the trap that makes S-03 a game: the
    credit tempts you to spend the battery before the order arrives."""
    start = max(1, order_turns[0] - APPEAL_HOURS)
    return list(range(start, order_turns[0]))


def turn_local_time(turn: int) -> str:
    return f"{(START_HOUR + turn) % 24:02d}:00"


def compile_s03(rows: list[HourlyLoad], responsive: bool = False) -> dict:
    annual_peak = max(r.total_mw for r in rows)
    year, month, day = find_peak_day(rows)

    day_rows = sorted(
        (r for r in rows if (r.year, r.month, r.day) == (year, month, day)),
        key=lambda r: r.period,
    )
    window = [r for r in day_rows if FIRST_PERIOD <= r.period <= FIRST_PERIOD + TURNS - 1]
    if len(window) != TURNS:
        raise ValueError(f"peak day {year}-{month:02d}-{day:02d} lacks periods {FIRST_PERIOD}..{FIRST_PERIOD + TURNS - 1}")

    all_sorted = sorted(r.total_mw for r in rows)
    watch_level = percentile(all_sorted, STATUS_WATCH_PCTL)
    emerg_level = percentile(all_sorted, STATUS_EMERG_PCTL)

    fracs = [r.total_mw / annual_peak for r in window]
    prices = [price_for(f) for f in fracs]

    loads = [r.total_mw for r in window]
    order_turns = order_window(loads)
    appeal_turns = appeal_window(order_turns)

    status: list[str] = []
    for i, r in enumerate(window):
        if i in order_turns or r.total_mw >= emerg_level:
            status.append("emergency")
        elif r.total_mw >= watch_level:
            status.append("watch")
        else:
            status.append("normal")

    # Campus IT demand: floor + cooling swing following the day's load shape.
    lo, hi = min(fracs), max(fracs)
    span = (hi - lo) or 1.0
    it_load = [round(IT_LOAD_BASE_MW + IT_LOAD_SWING_MW * (f - lo) / span, 1) for f in fracs]

    step_hours = 1.0
    baseline_cost = round(sum(mw * p * step_hours for mw, p in zip(it_load, prices, strict=True)), 2)

    pack = {
        "pack_version": PACK_VERSION,
        "scenario_id": "S-03",
        "title": "Curtailment Order",
        "substrate": "RTS-GMLC",
        "provenance": {
            "source": "GridMod/RTS-GMLC DAY_AHEAD_regional_Load.csv (public), regions summed",
            "source_url": RTS_GMLC_URL,
            "source_license": RTS_GMLC_LICENCE,
            "region": "system (regions 1+2+3)",
            "source_day": f"{year}-{month:02d}-{day:02d} (annual peak-load day), periods {FIRST_PERIOD}-{FIRST_PERIOD + TURNS - 1}",
            "notes": (
                "Prices derived, not observed: 22 + 60*L^3 $/MWh with a 4500*(L-0.93)/0.07 "
                "scarcity adder above L=0.93 of annual peak (ORDC-style). Status from annual "
                "load percentiles (watch>=p97, emergency>=p99.5); curtailment-order turns "
                "forced to emergency. Campus IT load authored, not observed: RTS-GMLC models "
                f"no data center, so the campus draws a {IT_LOAD_BASE_MW:g} MW floor plus a "
                f"{IT_LOAD_SWING_MW:g} MW cooling swing that follows the day's system load, "
                f"{IT_LOAD_BASE_MW:g} + {IT_LOAD_SWING_MW:g}*(L-Lmin)/(Lmax-Lmin) with L the "
                "hour's load as a fraction of annual peak and Lmin, Lmax its lowest and highest "
                "over the day's turns, rounded to 0.1 MW. Believable-not-certified per vision §5."
            ),
            # #221: a pack that reports system load must say what that series
            # counts, and it belongs HERE, beside the status_response that
            # exports it — not bolted on by a caller. RTS-GMLC is a synthetic
            # test system with no storage fleet and no separate
            # wholesale-storage metering, so nothing is excluded; recording
            # that we checked is the point. A real operator's series differs:
            # ERCOT meters Wholesale Storage Load separately, so its published
            # system load omits battery charging by construction and a pack
            # compiled from it would inherit the omission silently.
            **(
                {
                    "system_load_scope": {
                        "excluded": [],
                        "included": [
                            "all modelled regional demand in the RTS-GMLC day-ahead series"
                        ],
                        "definition_url": RTS_GMLC_LOAD_URL,
                    }
                }
                if responsive
                else {}
            ),
        },
        "brief_md": BRIEF_MD,
        "step_minutes": 60,
        "turns": TURNS,
        "start_hour_local": START_HOUR,
        "site": {
            "name": "Vulcan Flats Campus",
            "it_load_mw": it_load,
            "sla_usd_per_mwh_shed": SLA_USD_PER_MWH,
            "battery": dict(BATTERY),
            "diesel": dict(DIESEL),
        },
        "grid": {
            "price_usd_per_mwh": prices,
            "system_status": status,
            **(
                {
                    "price_slope_usd_per_mwh_per_mw": [
                        price_slope_per_mw(f, annual_peak) for f in fracs
                    ],
                    # 0004 v1 (#133): the same loads and percentile thresholds
                    # that derived the static strip, exported so the engine can
                    # grade REALIZED status including the campus's deviation.
                    # Note the static strip also forces order turns to
                    # emergency; the graded status deliberately does not — the
                    # order is policy, the grading is physics.
                    "status_response": {
                        "system_load_mw": [r.total_mw for r in window],
                        "watch_level_mw": watch_level,
                        "emergency_level_mw": emerg_level,
                    },
                    # 0004 v2 (#134): honest forecasts as data. Error model is
                    # pure persistence — every future hour is forecast at the
                    # current hour's price/status. Deterministic, documented,
                    # and famously wrong at cliffs: the scarcity afternoon
                    # arrives unannounced, exactly as it should.
                    "forecast": {
                        "price_usd_per_mwh": [
                            [prices[t]] * min(3, TURNS - 1 - t) for t in range(TURNS)
                        ],
                        "system_status": [
                            [status[t]] * min(3, TURNS - 1 - t) for t in range(TURNS)
                        ],
                    },
                }
                if responsive
                else {}
            ),
        },
        "events": [
            {
                "turn": appeal_turns[0] - 1,
                "type": "conservation_appeal",
                "credit_usd_per_mwh": APPEAL_CREDIT_USD_PER_MWH,
                "turns_active": appeal_turns,
                "notice_md": (
                    "**Conservation appeal.** The system operator requests voluntary demand "
                    f"reduction {turn_local_time(appeal_turns[0])}-"
                    f"{turn_local_time(appeal_turns[-1] + 1)}. Demonstrated reduction earns "
                    f"${APPEAL_CREDIT_USD_PER_MWH:.0f}/MWh if you opt in."
                ),
            },
            {
                "turn": order_turns[0] - 1,
                "type": "curtailment_order",
                "mw_requested": ORDER_MW,
                "turns_active": order_turns,
                "notice_md": (
                    f"**Emergency curtailment order.** Effective {turn_local_time(order_turns[0])}, "
                    f"reduce net grid draw by **{ORDER_MW:.0f} MW** for {ORDER_HOURS} hours. "
                    "Delivery is measured against your nominal draw; shortfall is public."
                ),
            },
        ],
        "scoring": {
            "score_version": SCORE_VERSION,
            "baseline_cost_usd": baseline_cost,
            "metrics": [
                {"id": "cost", "label": "Operating cost", "direction": "minimize", "unit": "USD"},
                {"id": "reliability", "label": "Reliability contribution", "direction": "maximize", "unit": "ratio"},
            ],
        },
    }
    return pack


class ObservationOutageDict(TypedDict):
    turns_active: list[int]
    frozen_fields: list[str]


ALLOWED_FROZEN_FIELDS = frozenset({"price_usd_per_mwh", "system_status", "forecast"})


def validate_observation_outages(outages: list[dict], turns: int) -> None:
    """Validate cross-field observation outage invariants: turn bounds, non-empty active turns, and valid field names."""
    assert isinstance(outages, list), "grid.observation_outage must be a list"
    for i, outage in enumerate(outages):
        turns_active = outage.get("turns_active")
        frozen_fields = outage.get("frozen_fields")
        assert isinstance(turns_active, list) and len(turns_active) > 0, (
            f"outage[{i}].turns_active must be a non-empty list of ints"
        )
        for t in turns_active:
            assert isinstance(t, int) and 1 <= t < turns, (
                f"outage[{i}].turns_active turn {t} out of bounds: must satisfy 1 <= t < {turns}"
            )
        assert isinstance(frozen_fields, list) and len(frozen_fields) > 0, (
            f"outage[{i}].frozen_fields must be a non-empty list"
        )
        for field in frozen_fields:
            assert field in ALLOWED_FROZEN_FIELDS, (
                f"outage[{i}].frozen_fields contains invalid field {field!r}; must be one of {sorted(ALLOWED_FROZEN_FIELDS)}"
            )
        # #697: whether the screen is told. Optional; absent means announced.
        announced = outage.get("announced", True)
        assert isinstance(announced, bool), f"outage[{i}].announced must be true or false"


class StockDeliveryDict(TypedDict):
    turn: int
    quantity: float


class StockDict(TypedDict, total=False):
    id: str
    label: str
    unit: str
    initial: float
    capacity: float
    burn_per_mwh_generated: float
    deliveries: list[StockDeliveryDict]
    burns_on: str


def validate_stocks(stocks: list[dict], turns: int, alternate_fuel: str | None = None) -> None:
    """Validate cross-field stock invariants: uniqueness, bounds, and delivery turn limits."""
    seen_ids = set()
    for stock in stocks:
        stock_id = stock["id"]
        if stock_id in seen_ids:
            raise ValueError(f"duplicate stock id '{stock_id}'")
        seen_ids.add(stock_id)
        if stock["initial"] < 0:
            raise ValueError(f"stock '{stock_id}' initial must be non-negative")
        if stock["capacity"] < 0:
            raise ValueError(f"stock '{stock_id}' capacity must be non-negative")
        if stock["initial"] > stock["capacity"]:
            raise ValueError(
                f"stock '{stock_id}' initial ({stock['initial']}) exceeds capacity ({stock['capacity']})"
            )
        if stock["burn_per_mwh_generated"] < 0:
            raise ValueError(f"stock '{stock_id}' burn_per_mwh_generated must be non-negative")
        # A stock bound to a fuel (#707) needs that fuel on the plant, or it never burns.
        if "burns_on" in stock and stock["burns_on"] != alternate_fuel:
            raise ValueError(
                f"stock '{stock_id}' burns_on {stock['burns_on']!r} names no alternate fuel on the plant"
            )
        seen_turns = set()
        for delivery in stock.get("deliveries", []):
            if delivery["quantity"] < 0:
                raise ValueError(f"stock '{stock_id}' delivery quantity must be non-negative")
            if not 0 <= delivery["turn"] < turns:
                raise ValueError(
                    f"stock '{stock_id}' delivery turn {delivery['turn']} outside bounds [0, {turns})"
                )
            # The engine applies one delivery per stock per turn, so a second is refused here.
            if delivery["turn"] in seen_turns:
                raise ValueError(f"stock '{stock_id}' has two deliveries on turn {delivery['turn']}")
            seen_turns.add(delivery["turn"])


def validate_commitments(commitments: list[dict], turns: int) -> None:
    """Cross-field invariants for commitments (#464) that the schema cannot express."""
    seen: set[str] = set()
    for c in commitments:
        cid = c["id"]
        if cid in seen:
            raise ValueError(f"commitment {cid}: duplicate id")
        if cid == "supply":
            # The local runner reads supply=id as the fuel supply choice (#469).
            raise ValueError("commitment supply: the id is reserved for the fuel supply choice")
        if cid == "fuel":
            # And fuel=id as a dual-fuel plant's fuel (#707).
            raise ValueError("commitment fuel: the id is reserved for the plant's fuel")
        seen.add(cid)
        if not 0 <= c["decision_turn"] < turns:
            raise ValueError(f"commitment {cid}: decision_turn outside 0..{turns - 1}")
        window = c["window"]
        if window != sorted(set(window)):
            raise ValueError(f"commitment {cid}: window must be ascending without repeats")
        if window[0] < c["decision_turn"] or window[-1] >= turns:
            raise ValueError(f"commitment {cid}: window must lie in decision_turn..{turns - 1}")
        if c["kind"] == "nomination":
            if "imbalance_usd_per_mwh" not in c:
                raise ValueError(f"commitment {cid}: a nomination needs imbalance_usd_per_mwh")
            if "tolerance_mw" in c and len(c["tolerance_mw"]) != len(window):
                raise ValueError(f"commitment {cid}: tolerance_mw length != window length")
            for key in ("capacity_usd_per_mw", "nonperformance_usd_per_mwh"):
                if key in c:
                    raise ValueError(f"commitment {cid}: a nomination takes no {key}")
        else:
            for key in ("capacity_usd_per_mw", "nonperformance_usd_per_mwh"):
                if key not in c:
                    raise ValueError(f"commitment {cid}: demand response needs {key}")
            for key in ("imbalance_usd_per_mwh", "tolerance_mw", "caps_gas"):
                if key in c:
                    raise ValueError(f"commitment {cid}: demand response takes no {key}")


def validate_flow_orders(pack: dict) -> None:
    """Cross-field invariants for flow orders (#635). An order tightens one
    nomination inside its window. Two on one commitment may not overlap,
    because the engine would have to choose between them. That an order is
    announced no later than its first active turn is checked with every event,
    and the screen relies on it: the observation then holds every order in
    force."""
    nominations = {
        c["id"]: c for c in pack.get("commitments", []) if c["kind"] == "nomination"
    }
    covered: dict[str, set[int]] = {}
    for ev in pack["events"]:
        if ev["type"] != "flow_order":
            continue
        cid = ev["commitment"]
        if cid not in nominations:
            raise ValueError(f"flow_order: {cid} is not a nomination in this pack")
        if not set(ev["turns_active"]) <= set(nominations[cid]["window"]):
            raise ValueError(f"flow_order: turns_active leaves the {cid} window")
        seen = covered.setdefault(cid, set())
        if seen & set(ev["turns_active"]):
            raise ValueError(f"flow_order: two orders on {cid} overlap")
        seen.update(ev["turns_active"])


def validate_emergency_orders(pack: dict) -> None:
    """Cross-field invariants for emergency orders (#465). Two may not share a
    turn: each says on its own terms when the permit is lifted, and the engine
    would have to choose between them. That an order is announced no later
    than its first active turn is checked with every event."""
    covered: set[int] = set()
    for ev in pack["events"]:
        if ev["type"] != "emergency_order":
            continue
        if covered & set(ev["turns_active"]):
            raise ValueError("emergency_order: two orders overlap")
        covered.update(ev["turns_active"])


def order_in_force(pack: dict, t: int) -> bool:
    """Whether an emergency order lifts the permit limit at turn t (#465): one
    is active and its condition holds against the published strip. The
    engine's orderInForce, for the optimizers."""
    status = pack["grid"]["system_status"][t]
    return any(
        ev["type"] == "emergency_order"
        and t in ev["turns_active"]
        and (ev["condition"] == "always" or status == "emergency")
        for ev in pack["events"]
    )


def tolerance_at(pack: dict, c: dict, t: int) -> float:
    """A nomination's free deviation at window turn t (#635): a flow order in
    force names it, otherwise the commitment's own term. The engine's
    toleranceAt, for the optimizers."""
    for ev in pack["events"]:
        if ev["type"] == "flow_order" and ev["commitment"] == c["id"] and t in ev["turns_active"]:
            return ev["tolerance_mw"]
    return c.get("tolerance_mw", [0.0] * len(c["window"]))[c["window"].index(t)]


def validate_fuel_supply(diesel: dict, turns: int) -> None:
    """Cross-field invariants for a fuel price series and supply options (#469)."""
    if "fuel_usd_per_mwh_series" in diesel and len(diesel["fuel_usd_per_mwh_series"]) != turns:
        raise ValueError("site.diesel.fuel_usd_per_mwh_series: length != turns")
    seen: set[str] = set()
    for option in diesel.get("supply_options", []):
        oid = option["id"]
        if oid in seen:
            raise ValueError(f"supply option {oid}: duplicate id")
        seen.add(oid)
        if len(option["available_mw"]) != turns:
            raise ValueError(f"supply option {oid}: available_mw length != turns")
    # "gas" is what Action.fuel names the first fuel (#707); the schema refuses
    # it too, and this says why to a contributor reading the compiler.
    alt = diesel.get("alternate_fuel")
    if alt is not None and alt["id"] == "gas":
        raise ValueError("site.diesel.alternate_fuel: the id 'gas' names the plant's first fuel")


def validate_pack(pack: dict) -> None:
    schema = json.loads(PACK_SCHEMA_PATH.read_text())
    validate(instance=pack, schema=schema)
    # Cross-field invariants the schema cannot express:
    n = pack["turns"]
    if "stocks" in pack.get("site", {}):
        alt = pack["site"]["diesel"].get("alternate_fuel")
        validate_stocks(pack["site"]["stocks"], n, alt["id"] if alt else None)
    validate_fuel_supply(pack["site"]["diesel"], n)
    for path, arr in (
        ("site.it_load_mw", pack["site"]["it_load_mw"]),
        ("grid.price_usd_per_mwh", pack["grid"]["price_usd_per_mwh"]),
        ("grid.system_status", pack["grid"]["system_status"]),
    ):
        if len(arr) != n:
            raise ValueError(f"{path}: length {len(arr)} != turns {n}")
    if "coach_md" in pack and len(pack["coach_md"]) != n:
        raise ValueError(f"coach_md: length {len(pack['coach_md'])} != turns {n}")
    if "price_slope_usd_per_mwh_per_mw" in pack["grid"] and len(pack["grid"]["price_slope_usd_per_mwh_per_mw"]) != n:
        raise ValueError("grid.price_slope_usd_per_mwh_per_mw: length != turns")
    if "import_limit_mw" in pack["grid"] and len(pack["grid"]["import_limit_mw"]) != n:
        raise ValueError("grid.import_limit_mw: length != turns")
    for ev in pack["events"]:
        for t in [ev["turn"], *ev["turns_active"]]:
            if not 0 <= t < n:
                raise ValueError(f"event {ev['type']}: turn {t} outside 0..{n - 1}")
        if ev["turn"] > min(ev["turns_active"]):
            raise ValueError(f"event {ev['type']}: announced after it starts")
    if "commitments" in pack:
        validate_commitments(pack["commitments"], n)
    validate_flow_orders(pack)
    validate_emergency_orders(pack)
    if "observation_outage" in pack.get("grid", {}):
        validate_observation_outages(pack["grid"]["observation_outage"], pack["turns"])
    # A pack that reports system load must say what that series counts (#221).
    # The community reading divides the neighbours' bill across others'
    # consumption derived from it, so an unstated exclusion silently
    # understates the denominator and overstates the number a council member
    # is asked to read.
    if "status_response" in pack["grid"]:
        scope = pack.get("provenance", {}).get("system_load_scope")
        if scope is None:
            raise ValueError(
                "grid.status_response is present, so provenance.system_load_scope "
                "must state what the published load series excludes (#221). An "
                "empty `excluded` list is a valid answer; silence is not."
            )
        if len(pack["grid"]["status_response"]["system_load_mw"]) != n:
            raise ValueError("grid.status_response.system_load_mw: length != turns")


def compile_s00() -> dict:
    """S-00 · First Shift — the tutorial (Palaestra #62, first brick of #7).

    Fully synthetic, deliberately round numbers so the arithmetic teaches:
    a flat 100 MW campus, a 50 MW / 100 MWh battery, six turns, one polite
    appeal, one single-hour 20 MW order. The paidotribes speaks every turn
    via coach_md. Same engine, same contract — scenarios stay data.
    """
    turns = 6
    it_load = [100.0] * turns
    prices = [45.0, 50.0, 60.0, 400.0, 900.0, 120.0]
    status = ["normal", "normal", "normal", "watch", "emergency", "normal"]
    baseline = round(sum(mw * p for mw, p in zip(it_load, prices, strict=True)), 2)

    pack = {
        "pack_version": PACK_VERSION,
        "scenario_id": "S-00",
        "title": "First Shift",
        "substrate": "synthetic",
        "provenance": {
            "source": "hand-authored teaching numbers (no external dataset)",
            "source_license": HAND_AUTHORED_LICENCE,
            "region": "a campus of round numbers",
            "source_day": "any morning you choose",
            "notes": "Deliberately clean arithmetic: flat 100 MW load, price strip 45/50/60/400/900/120. Tutorial per Palaestra #62.",
        },
        "brief_md": (
            "## S-00 · First Shift\n\n"
            "Your first morning running a **100 MW campus**. Six hours, small stakes,\n"
            "and the paidotribes at your elbow the whole time.\n\n"
            "**Your assets:** a 50 MW / 100 MWh battery and a 20 MW natural-gas generator\n"
            "with 2 permitted run-hours. Same rules as the real day: two scores,\n"
            "published, in tension.\n\n"
            "Nothing here can hurt you. That is what practice is for.\n"
        ),
        "coach_md": [
            "Prices are low this hour. This is when a campus fills its battery. Press **Fill −50**, then Commit. (Negative numbers fill; positive numbers drain.)",
            "Still cheap. Top the battery off with **Fill −50** again, or commit zeros; zeros are always safe.",
            "A **conservation appeal** just arrived: voluntary, and it pays. Tick the checkbox and **Drain +30**. You earn a credit for every megawatt you hand back.",
            "Watch the forecast: the price is about to spike. Hold your remaining charge, commit zeros, and let the storm come to you.",
            "An **order** this time, not optional. They asked for 20 MW. **Drain +50** covers it four times over at the day's worst price. Watch the green bar appear on the chart.",
            "The day cools off. Zeros to the finish, and then read your settlement: both numbers, and where they came from.",
        ],
        "step_minutes": 60,
        "turns": turns,
        "start_hour_local": 6,
        "site": {
            "name": "Practice Yard",
            "it_load_mw": it_load,
            "sla_usd_per_mwh_shed": SLA_USD_PER_MWH,
            "battery": {"power_mw": 50.0, "energy_mwh": 100.0, "efficiency_rt": 0.9, "initial_soc": 0.0},
            "diesel": {"power_mw": 20.0, "permit_hours_remaining": 2, "fuel_usd_per_mwh": 120.0},
        },
        "grid": {"price_usd_per_mwh": prices, "system_status": status},
        "events": [
            {
                "turn": 1,
                "type": "conservation_appeal",
                "credit_usd_per_mwh": 100.0,
                "turns_active": [2, 3],
                "notice_md": (
                    "**Conservation appeal.** The system operator requests voluntary demand "
                    "reduction 08:00-10:00. Demonstrated reduction earns $100/MWh if you opt in."
                ),
            },
            {
                "turn": 3,
                "type": "curtailment_order",
                "mw_requested": 20.0,
                "turns_active": [4],
                "notice_md": (
                    "**Emergency curtailment order.** Effective 10:00, reduce net grid draw by "
                    "**20 MW** for one hour. Delivery is measured against your nominal draw."
                ),
            },
        ],
        "scoring": {
            "score_version": SCORE_VERSION,
            "baseline_cost_usd": baseline,
            "metrics": [
                {"id": "cost", "label": "Operating cost", "direction": "minimize", "unit": "USD"},
                {"id": "reliability", "label": "Reliability contribution", "direction": "maximize", "unit": "ratio"},
            ],
        },
    }
    return pack


S10_BRIEF_MD = """\
## S-10 · Two Peaks

A winter morning, and the day has two summits.

Cold snaps stress a grid twice: once when the region wakes and heats, and
again when it comes home at dusk. You face both, with less than you had on
the summer day: the battery starts a quarter full, and the gas plant holds
**2 permitted run-hours** for the entire day. The system operator will
order relief at both peaks. One tank, two permits, two crises: what you
spend on the morning you cannot spend on the evening.

The forecast assumes the next hours look like this one. Winter mornings
do not work that way.

Prices here measure scarcity against the season's capability, not the
summer peak: winter capacity is thinner, and the scenario's source notes
say by how much. Stars are live on this board; the optimum is solved and
engine-verified, and full relief at both peaks is the price of any medal.
"""


def compile_s10(rows: list[HourlyLoad]) -> dict:
    """S-10 · Two Peaks (#161): a winter double-peak day from the same public
    RTS-GMLC series. Seasonal normalization, documented: L is measured
    against WINTER capability (the Dec-Jan-Feb maximum), modelling the
    maintenance-season reality that winter available capacity is lower.
    Scarcity and status thresholds are winter-relative for the same reason.
    Slope-free, so the exact optimizer certifies the gold line."""
    winter = [r for r in rows if r.month in (12, 1, 2)]
    winter_peak = max(r.total_mw for r in winter)

    def day_rows(y: int, m: int, d: int) -> list[HourlyLoad]:
        return sorted(
            (r for r in winter if (r.year, r.month, r.day) == (y, m, d)),
            key=lambda r: r.period,
        )

    # The twin-peaks day: maximize the LOWER of the two peaks, so both
    # summits are genuinely tall. Morning = periods 7-12, evening = 17-22.
    def twin_score(day: list[HourlyLoad]) -> float:
        morning = max((r.total_mw for r in day if 7 <= r.period <= 12), default=0.0)
        evening = max((r.total_mw for r in day if 17 <= r.period <= 22), default=0.0)
        return min(morning, evening)

    days = sorted({(r.year, r.month, r.day) for r in winter})
    y, m, d = max(days, key=lambda k: twin_score(day_rows(*k)))

    first_period, turns = 7, 16  # 06:00 through 21:00 local, hourly
    window = [r for r in day_rows(y, m, d) if first_period <= r.period <= first_period + turns - 1]
    assert len(window) == turns, f"winter day {y}-{m:02d}-{d:02d} lacks periods"

    fracs = [r.total_mw / winter_peak for r in window]
    prices = [price_for(f) for f in fracs]
    loads = [r.total_mw for r in window]

    # Morning order: the tightest 2 contiguous hours in the first six turns.
    def best_window(lo: int, hi: int, length: int) -> list[int]:
        starts = range(lo, hi - length + 2)
        s0 = max(starts, key=lambda s: sum(loads[s : s + length]))
        return list(range(s0, s0 + length))

    morning_order = best_window(0, 5, 2)
    evening_order = best_window(8, turns - 1, 3)
    # The appeal sits in the valley between the crises, disjoint from both
    # (#84 stays latent: windows never overlap).
    valley_lo, valley_hi = morning_order[-1] + 1, evening_order[0] - 1
    assert valley_hi - valley_lo >= 2, "no valley between the peaks"
    appeal = best_window(valley_lo, valley_hi, 3) if valley_hi - valley_lo >= 2 else []
    appeal = appeal[:3]

    winter_sorted = sorted(r.total_mw for r in winter)
    watch_level = percentile(winter_sorted, STATUS_WATCH_PCTL)
    emerg_level = percentile(winter_sorted, STATUS_EMERG_PCTL)
    status: list[str] = []
    for i, r in enumerate(window):
        if i in morning_order or i in evening_order or r.total_mw >= emerg_level:
            status.append("emergency")
        elif r.total_mw >= watch_level:
            status.append("watch")
        else:
            status.append("normal")

    lo_f, hi_f = min(fracs), max(fracs)
    span = (hi_f - lo_f) or 1.0
    it_load = [round(IT_LOAD_BASE_MW + IT_LOAD_SWING_MW * (f - lo_f) / span, 1) for f in fracs]
    baseline_cost = round(sum(mw * p for mw, p in zip(it_load, prices, strict=True)), 2)

    def turn_local(t: int) -> str:
        return f"{6 + t:02d}:00"

    pack = {
        "pack_version": "0.1.0",
        "scenario_id": "S-10",
        "title": "Two Peaks",
        "substrate": "RTS-GMLC",
        "provenance": {
            "source": "NREL RTS-GMLC DAY_AHEAD_regional_Load.csv (public), all three regions summed",
            "source_url": RTS_GMLC_URL,
            "source_license": RTS_GMLC_LICENCE,
            "region": "RTS-GMLC composite system",
            "source_day": f"{y}-{m:02d}-{d:02d} (winter twin-peaks day: maximizes the lower of the two daily summits), periods {first_period}-{first_period + turns - 1}",
            "notes": (
                "Same documented price curve as S-03 with SEASONAL normalization: L = load / winter "
                "(Dec-Jan-Feb) peak rather than annual peak, modelling maintenance-season capability. "
                "Status thresholds are winter percentiles (watch>=p97, emergency>=p99.5); order turns "
                "forced to emergency. Forecast is PURE PERSISTENCE (0004 v2): every future hour "
                "forecast at the current hour's value, deterministic and blind at both cliffs. "
                "Two disjoint curtailment orders (morning 2h x 30 MW, evening 3h x 40 MW) with the "
                "conservation appeal in the valley between; windows never overlap (#84 latent). "
                "Slope-free: the exact optimizer certifies the gold line."
            ),
        },
        "brief_md": S10_BRIEF_MD,
        "step_minutes": 60,
        "turns": turns,
        "start_hour_local": 6,
        "site": {
            "name": "Vulcan Flats Campus",
            "it_load_mw": it_load,
            "sla_usd_per_mwh_shed": SLA_USD_PER_MWH,
            "battery": {"power_mw": 100.0, "energy_mwh": 300.0, "efficiency_rt": 0.88, "initial_soc": 0.25},
            "diesel": {"power_mw": 60.0, "permit_hours_remaining": 2, "fuel_usd_per_mwh": 65.0},
        },
        "grid": {
            "price_usd_per_mwh": prices,
            "system_status": status,
            "forecast": {
                "price_usd_per_mwh": [[prices[t]] * min(3, turns - 1 - t) for t in range(turns)],
                "system_status": [[status[t]] * min(3, turns - 1 - t) for t in range(turns)],
            },
        },
        "events": [
            {
                "turn": max(0, morning_order[0] - 1),
                "type": "curtailment_order",
                "mw_requested": 30.0,
                "turns_active": morning_order,
                "notice_md": (
                    f"**Emergency curtailment order.** Effective {turn_local(morning_order[0])}, reduce "
                    f"net grid draw by **30 MW** for {len(morning_order)} hours. The morning peak is here."
                ),
            },
            {
                "turn": appeal[0] - 1,
                "type": "conservation_appeal",
                "credit_usd_per_mwh": APPEAL_CREDIT_USD_PER_MWH,
                "turns_active": appeal,
                "notice_md": (
                    f"**Conservation appeal.** Voluntary reduction requested {turn_local(appeal[0])}-"
                    f"{turn_local(appeal[-1] + 1)}, credited at $150/MWh. The evening peak is coming."
                ),
            },
            {
                "turn": evening_order[0] - 1,
                "type": "curtailment_order",
                "mw_requested": 40.0,
                "turns_active": evening_order,
                "notice_md": (
                    f"**Emergency curtailment order.** Effective {turn_local(evening_order[0])}, reduce "
                    f"net grid draw by **40 MW** for {len(evening_order)} hours. The second summit."
                ),
            },
        ],
        "scoring": {
            "score_version": SCORE_VERSION,
            "baseline_cost_usd": baseline_cost,
            "metrics": [
                {"id": "cost", "label": "Operating cost", "direction": "minimize", "unit": "USD"},
                {"id": "reliability", "label": "Reliability contribution", "direction": "maximize", "unit": "ratio"},
            ],
        },
    }
    return pack


S07_BRIEF_MD = """\
## S-07 · Heat Dome

Three days. The heat does not break at sunset.

This is the hardest seventy-two-hour stretch in the source data's year, played
straight through: three afternoons of scarcity, three conservation appeals,
three curtailment orders, and one battery that must survive all of it. Six
permitted gas hours for the whole event. Sustained scarcity is a different
game from an afternoon of it: the question is never this hour, it is
whether you will still have options tomorrow.

The forecast assumes the next hours look like this one. Across three days,
that assumption fails you at every dawn and every dusk.

Stars are live, and the bar is reachable: the optimum was solved as an
exact mixed-integer program and replayed through the engine to the penny.
Full delivery of all three orders is the price of any medal.
"""


def compile_s07(rows: list[HourlyLoad]) -> dict:
    """S-07 · Heat Dome (#163): the year's worst 72 consecutive hours, played
    straight through. Annual-peak normalization (same as S-03): a heat dome
    IS the summer scarcity archetype. Registry v1 note: the entry imagines a
    full week; this compiles the worst three days — the endurance statement
    at a humane number of commits — and records the amendment."""
    turns = 72
    by_time = sorted(rows, key=lambda r: (r.year, r.month, r.day, r.period))
    annual_peak = max(r.total_mw for r in rows)

    # Worst 72h stretch, aligned to midnight so the days read as days.
    starts = [i for i in range(0, len(by_time) - turns + 1) if by_time[i].period == 1]
    i0 = max(starts, key=lambda i: sum(r.total_mw for r in by_time[i : i + turns]))
    window = by_time[i0 : i0 + turns]
    d0 = window[0]

    fracs = [r.total_mw / annual_peak for r in window]
    prices = [price_for(f) for f in fracs]
    loads = [r.total_mw for r in window]

    # Each day's order: the tightest 3 contiguous hours of that day.
    def day_slice(k: int) -> tuple[int, int]:
        return k * 24, (k + 1) * 24 - 1

    def best_window(lo: int, hi: int, length: int) -> list[int]:
        s0 = max(range(lo, hi - length + 2), key=lambda s: sum(loads[s : s + length]))
        return list(range(s0, s0 + length))

    orders = []
    appeals = []
    for k in range(3):
        lo, hi = day_slice(k)
        ow = best_window(lo, hi, 3)
        # The appeal precedes the order, disjoint (#84 latent): the 3 hours
        # ending just before the order window opens.
        ap = [t for t in range(ow[0] - 3, ow[0]) if t >= lo]
        orders.append(ow)
        appeals.append(ap)

    annual_sorted = sorted(r.total_mw for r in rows)
    watch_level = percentile(annual_sorted, STATUS_WATCH_PCTL)
    emerg_level = percentile(annual_sorted, STATUS_EMERG_PCTL)
    order_turns = {t for ow in orders for t in ow}
    status: list[str] = []
    for i, r in enumerate(window):
        if i in order_turns or r.total_mw >= emerg_level:
            status.append("emergency")
        elif r.total_mw >= watch_level:
            status.append("watch")
        else:
            status.append("normal")

    lo_f, hi_f = min(fracs), max(fracs)
    span = (hi_f - lo_f) or 1.0
    it_load = [round(IT_LOAD_BASE_MW + IT_LOAD_SWING_MW * (f - lo_f) / span, 1) for f in fracs]
    baseline_cost = round(sum(mw * p for mw, p in zip(it_load, prices, strict=True)), 2)

    def turn_local(t: int) -> str:
        return f"day {t // 24 + 1}, {t % 24:02d}:00"

    escalation = [30.0, 40.0, 40.0]
    events: list[dict] = []
    for k in range(3):
        if appeals[k]:
            events.append(
                {
                    "turn": max(0, appeals[k][0] - 1),
                    "type": "conservation_appeal",
                    "credit_usd_per_mwh": APPEAL_CREDIT_USD_PER_MWH,
                    "turns_active": appeals[k],
                    "notice_md": (
                        f"**Conservation appeal.** Voluntary reduction requested from "
                        f"{turn_local(appeals[k][0])}, credited at $150/MWh. "
                        f"The afternoon peak of day {k + 1} is coming."
                    ),
                }
            )
        events.append(
            {
                "turn": max(0, orders[k][0] - 1),
                "type": "curtailment_order",
                "mw_requested": escalation[k],
                "turns_active": orders[k],
                "notice_md": (
                    f"**Emergency curtailment order.** Effective {turn_local(orders[k][0])}, "
                    f"reduce net grid draw by **{escalation[k]:.0f} MW** for "
                    f"{len(orders[k])} hours. Day {k + 1} of the dome."
                ),
            }
        )

    pack = {
        "pack_version": "0.1.0",
        "scenario_id": "S-07",
        "title": "Heat Dome",
        "substrate": "RTS-GMLC",
        "provenance": {
            "source": "NREL RTS-GMLC DAY_AHEAD_regional_Load.csv (public), all three regions summed",
            "source_url": RTS_GMLC_URL,
            "source_license": RTS_GMLC_LICENCE,
            "region": "RTS-GMLC composite system",
            "source_day": (
                f"{d0.year}-{d0.month:02d}-{d0.day:02d} + 2 days "
                "(the year's worst 72 consecutive hours by summed load, midnight-aligned)"
            ),
            "notes": (
                "Same documented price curve and annual-peak normalization as S-03: the heat "
                "dome IS the summer scarcity archetype. Status thresholds are annual "
                "percentiles; order turns forced to emergency. Forecast is PURE PERSISTENCE "
                "(0004 v2), blind at every dawn and dusk of the event. One appeal and one "
                "order per day, escalating 30/40/40 MW, all windows disjoint (#84 latent). "
                "Registry v1 amendment: the S-07 entry imagines a full week; this pack plays "
                "the worst three days. optimal_cost_usd solved as an exact MILP (HiGHS via "
                "scipy) and engine-verified by parity test."
            ),
        },
        "brief_md": S07_BRIEF_MD,
        "step_minutes": 60,
        "turns": turns,
        "start_hour_local": 0,
        "site": {
            "name": "Vulcan Flats Campus",
            "it_load_mw": it_load,
            "sla_usd_per_mwh_shed": SLA_USD_PER_MWH,
            "battery": dict(BATTERY),
            "diesel": {"power_mw": 60.0, "permit_hours_remaining": 6, "fuel_usd_per_mwh": 65.0},
        },
        "grid": {
            "price_usd_per_mwh": prices,
            "system_status": status,
            "forecast": {
                "price_usd_per_mwh": [[prices[t]] * min(3, turns - 1 - t) for t in range(turns)],
                "system_status": [[status[t]] * min(3, turns - 1 - t) for t in range(turns)],
            },
        },
        "events": events,
        "scoring": {
            "score_version": SCORE_VERSION,
            "baseline_cost_usd": baseline_cost,
            "metrics": [
                {"id": "cost", "label": "Operating cost", "direction": "minimize", "unit": "USD"},
                {"id": "reliability", "label": "Reliability contribution", "direction": "maximize", "unit": "ratio"},
            ],
        },
    }
    return pack


# --- S-11 The Consumables Cliff (#440) ---------------------------------------
# The Winter 2026 Arctic Events report (FERC/NERC joint staff, pp. 18-19):
# units built to run for hours ran for days, and some nearly exhausted their
# demineralized water and other non-fuel consumables before their fuel. The
# water is injected for NOx control; at a water-to-fuel mass ratio near one
# and a heat rate near 10 MMBtu/MWh that is about a quarter of a cubic meter
# per MWh. A teaching number of the right order, not a plant's datasheet.
S11_WATER_M3_PER_MWH = 0.25
S11_WATER_INITIAL_M3 = 90.0     # 360 MWh: six hours at full output
S11_WATER_CAPACITY_M3 = 120.0
S11_TRUCK_M3 = 90.0             # one refill: six more hours at full output
S11_TRUCK_PROMISED_TURN = 30    # day 2, 06:00, as the brief promises
# Day 3, 21:00: after the third order, so the starting tank must last all
# three days. A sweep on 2026-11-04 placed it: believe the promise and the
# day-1 optimum burns 60 m3 rather than 30 (tests/unit/test_s11_pack.py holds
# that), and the sweep estimated that a player who does so and then plays
# perfectly finishes about 1.7% above the certified line, outside gold's 1%.
S11_TRUCK_ACTUAL_TURN = 69
S11_PERMIT_HOURS = 24           # permits to spare: the tank binds first
# Day 2's appeal notice carries it (S-23, #473, takes it back out).
S11_TRUCK_NOTE = " The water truck due at dawn is late, and the carrier names no new time."

S11_BRIEF_MD = """\
## S-11 · The Consumables Cliff

The cold lasts three days, and the gas plant has fuel to spare.

Winter demand in the source data runs high for three evenings in a row:
three conservation appeals, three curtailment orders, and one battery that
must survive all of it. You hold twenty-four permitted gas hours, four times
what the heat dome allowed, and the fuel line is full.

The plant also injects demineralized water to hold down its emissions, and
every megawatt-hour it makes drains the tank. The tank holds ninety cubic
meters, which is six hours at full output. The water carrier has promised a
refill of ninety cubic meters at dawn on day two.

The forecast assumes the next hours look like this one.

Stars are live. An exact mixed-integer program found the optimum with the
tank in it. The engine replayed that line to the penny. Full delivery of
all three orders is the price of any medal.
"""


def compile_s11(rows: list[HourlyLoad]) -> dict:
    """S-11 · The Consumables Cliff (#440): a three-day cold event on the S-07
    pattern. The gas plant has fuel and permit hours to spare; its water tank
    drains with every MWh it makes, and the refill the brief promises arrives
    a day late. Winter normalization as S-10: the worst 72 consecutive winter
    hours, measured against the Dec-Jan-Feb peak. The MILP models the stock
    (#582) and certifies the line."""
    turns = 72
    winter = [r for r in rows if r.month in (12, 1, 2)]
    winter_peak = max(r.total_mw for r in winter)
    by_day: dict[tuple[int, int, int], list[HourlyLoad]] = {}
    for r in winter:
        by_day.setdefault((r.year, r.month, r.day), []).append(r)
    for day in by_day.values():
        day.sort(key=lambda r: r.period)

    # Three calendar-consecutive winter days, each with all 24 periods.
    def run_from(key: tuple[int, int, int]) -> list[HourlyLoad] | None:
        d0 = datetime.date(*key)
        out: list[HourlyLoad] = []
        for k in range(3):
            d = d0 + datetime.timedelta(days=k)
            day = by_day.get((d.year, d.month, d.day))
            if day is None or len(day) != 24:
                return None
            out.extend(day)
        return out

    runs = {key: run for key in sorted(by_day) if (run := run_from(key)) is not None}
    start = max(runs, key=lambda key: sum(r.total_mw for r in runs[key]))
    window = runs[start]

    fracs = [r.total_mw / winter_peak for r in window]
    prices = [price_for(f) for f in fracs]
    loads = [r.total_mw for r in window]

    def best_window(lo: int, hi: int, length: int) -> list[int]:
        s0 = max(range(lo, hi - length + 2), key=lambda s: sum(loads[s : s + length]))
        return list(range(s0, s0 + length))

    orders, appeals = [], []
    for k in range(3):
        lo, hi = k * 24, (k + 1) * 24 - 1
        ow = best_window(lo, hi, 3)
        orders.append(ow)
        appeals.append([t for t in range(ow[0] - 3, ow[0]) if t >= lo])

    winter_sorted = sorted(r.total_mw for r in winter)
    watch_level = percentile(winter_sorted, STATUS_WATCH_PCTL)
    emerg_level = percentile(winter_sorted, STATUS_EMERG_PCTL)
    order_turns = {t for ow in orders for t in ow}
    status: list[str] = []
    for i, r in enumerate(window):
        if i in order_turns or r.total_mw >= emerg_level:
            status.append("emergency")
        elif r.total_mw >= watch_level:
            status.append("watch")
        else:
            status.append("normal")

    lo_f, hi_f = min(fracs), max(fracs)
    span = (hi_f - lo_f) or 1.0
    it_load = [round(IT_LOAD_BASE_MW + IT_LOAD_SWING_MW * (f - lo_f) / span, 1) for f in fracs]
    baseline_cost = round(sum(mw * p for mw, p in zip(it_load, prices, strict=True)), 2)

    def turn_local(t: int) -> str:
        return f"day {t // 24 + 1}, {t % 24:02d}:00"

    escalation = [30.0, 40.0, 40.0]
    # The first notice after the promised hour says the truck has not come,
    # which the tank has already shown. It names no new time, because the
    # carrier has none to give.
    truck_note = S11_TRUCK_NOTE
    assert appeals[1] and appeals[1][0] - 1 > S11_TRUCK_PROMISED_TURN, "day-2 appeal precedes the promise"
    events: list[dict] = []
    for k in range(3):
        if appeals[k]:
            events.append(
                {
                    "turn": max(0, appeals[k][0] - 1),
                    "type": "conservation_appeal",
                    "credit_usd_per_mwh": APPEAL_CREDIT_USD_PER_MWH,
                    "turns_active": appeals[k],
                    "notice_md": (
                        f"**Conservation appeal.** Voluntary reduction requested from "
                        f"{turn_local(appeals[k][0])}, credited at $150/MWh. "
                        f"The evening peak of day {k + 1} is coming."
                        + (truck_note if k == 1 else "")
                    ),
                }
            )
        events.append(
            {
                "turn": max(0, orders[k][0] - 1),
                "type": "curtailment_order",
                "mw_requested": escalation[k],
                "turns_active": orders[k],
                "notice_md": (
                    f"**Emergency curtailment order.** Effective {turn_local(orders[k][0])}, "
                    f"reduce net grid draw by **{escalation[k]:.0f} MW** for "
                    f"{len(orders[k])} hours. This is day {k + 1} of the cold."
                ),
            }
        )

    y, m, d = start
    pack = {
        "pack_version": "0.1.0",
        "scenario_id": "S-11",
        "title": "The Consumables Cliff",
        "substrate": "RTS-GMLC",
        "provenance": {
            "source": "NREL RTS-GMLC DAY_AHEAD_regional_Load.csv (public), all three regions summed",
            "source_url": RTS_GMLC_URL,
            "source_license": RTS_GMLC_LICENCE,
            "region": "RTS-GMLC composite system",
            "source_day": (
                f"{y}-{m:02d}-{d:02d} + 2 days "
                "(the worst 72 consecutive winter hours by summed load, midnight-aligned)"
            ),
            "notes": (
                "Same documented price curve as S-03 with S-10's SEASONAL normalization: "
                "L = load / winter (Dec-Jan-Feb) peak. Status thresholds are winter "
                "percentiles; order turns forced to emergency. Forecast is PURE PERSISTENCE "
                "(0004 v2). One appeal and one order per day, escalating 30/40/40 MW, all "
                "windows disjoint (#84 latent). Situation from the Winter 2026 Arctic Events "
                "report (FERC/NERC joint staff, pp. 18-19): non-fuel consumables ran short "
                "before fuel. The gas plant's demineralized water stock (#462) burns "
                f"{S11_WATER_M3_PER_MWH} m3 per MWh, a teaching number of the right order for "
                "NOx-control water injection. The brief promises the refill at "
                f"{turn_local(S11_TRUCK_PROMISED_TURN)}; the pack delivers it at "
                f"{turn_local(S11_TRUCK_ACTUAL_TURN)}, and the server withholds delivery "
                "turns from the player. optimal_cost_usd solved as an exact MILP (HiGHS "
                "via scipy) with the stock modelled (#582), engine-verified by parity test."
            ),
        },
        "brief_md": S11_BRIEF_MD,
        "step_minutes": 60,
        "turns": turns,
        "start_hour_local": 0,
        "site": {
            "name": "Vulcan Flats Campus",
            "it_load_mw": it_load,
            "sla_usd_per_mwh_shed": SLA_USD_PER_MWH,
            "battery": dict(BATTERY),
            "diesel": {
                "power_mw": 60.0,
                "permit_hours_remaining": S11_PERMIT_HOURS,
                "fuel_usd_per_mwh": 65.0,
            },
            "stocks": [
                {
                    "id": "water",
                    "label": "Demineralized water",
                    "unit": "m³",
                    "initial": S11_WATER_INITIAL_M3,
                    "capacity": S11_WATER_CAPACITY_M3,
                    "burn_per_mwh_generated": S11_WATER_M3_PER_MWH,
                    "deliveries": [{"turn": S11_TRUCK_ACTUAL_TURN, "quantity": S11_TRUCK_M3}],
                }
            ],
        },
        "grid": {
            "price_usd_per_mwh": prices,
            "system_status": status,
            "forecast": {
                "price_usd_per_mwh": [[prices[t]] * min(3, turns - 1 - t) for t in range(turns)],
                "system_status": [[status[t]] * min(3, turns - 1 - t) for t in range(turns)],
            },
        },
        "events": events,
        "scoring": {
            "score_version": SCORE_VERSION,
            "baseline_cost_usd": baseline_cost,
            "metrics": [
                {"id": "cost", "label": "Operating cost", "direction": "minimize", "unit": "USD"},
                {"id": "reliability", "label": "Reliability contribution", "direction": "maximize", "unit": "ratio"},
            ],
        },
    }
    return pack


# --- S-12 Amplified (#443) ----------------------------------------------------
# The Winter 2026 Arctic Events report (pp. 13-15): load was under-forecast,
# and where the weather error and the load-model error moved the same way they
# amplified each other. Both components grow with lead time and share a sign,
# so every forecast is low and each re-forecast is higher than the last.
# Weather: about 2 F of temperature miss per hour of lead at 0.75% of demand
# per degree (the report gives 0.5 to 1%, p. 6). Load model: 1% per hour of
# lead. At the three-hour horizon the stack is 7.5%, inside the report's
# 3.9% to 10.5% day-ahead range (p. 13).
S12_WEATHER_ERR_PER_LEAD_H = 0.015
S12_MODEL_ERR_PER_LEAD_H = 0.010
S12_FORECAST_HOURS = 3

S12_BRIEF_MD = """\
## S-12 · Amplified

This is the winter's peak day, and every forecast on the board is low.

The board looks three hours ahead. Each forecast hour carries two errors that
point the same way: the weather turns colder than predicted, and the load
model underestimates what the region draws in the cold. Each new forecast for
an hour comes in higher than the last one, and the hour itself comes in
higher still.

Your assets are the S-03 set: a 100 MW / 400 MWh battery and a 60 MW
natural-gas plant with four permitted run-hours. The system operator will ask
for help, first politely, then not.

Stars are live. The exact optimizer plays the day as it happened.
"""


def s12_under_forecast(lead_h: int) -> float:
    """The fraction by which a forecast `lead_h` hours ahead understates load."""
    return (S12_WEATHER_ERR_PER_LEAD_H + S12_MODEL_ERR_PER_LEAD_H) * lead_h


def compile_s12(rows: list[HourlyLoad]) -> dict:
    """S-12 · Amplified (#443): the S-03 shape on the winter peak day, with a
    forecast compiled from two stacked under-forecast errors. Winter
    normalization as S-10. The fog is data: settlement reads the actuals, so
    the enumerator certifies the line exactly as it does S-03's."""
    winter = [r for r in rows if r.month in (12, 1, 2)]
    winter_peak = max(r.total_mw for r in winter)
    peak = max(winter, key=lambda r: r.total_mw)
    y, m, d = peak.year, peak.month, peak.day
    day_rows = sorted(
        (r for r in winter if (r.year, r.month, r.day) == (y, m, d)), key=lambda r: r.period
    )
    window = [r for r in day_rows if FIRST_PERIOD <= r.period <= FIRST_PERIOD + TURNS - 1]
    assert len(window) == TURNS, f"winter peak day {y}-{m:02d}-{d:02d} lacks periods"

    loads = [r.total_mw for r in window]
    fracs = [mw / winter_peak for mw in loads]
    prices = [price_for(f) for f in fracs]
    order_turns = order_window(loads)
    appeal_turns = appeal_window(order_turns)

    winter_sorted = sorted(r.total_mw for r in winter)
    watch_level = percentile(winter_sorted, STATUS_WATCH_PCTL)
    emerg_level = percentile(winter_sorted, STATUS_EMERG_PCTL)

    def graded(mw: float) -> str:
        if mw >= emerg_level:
            return "emergency"
        return "watch" if mw >= watch_level else "normal"

    # The actual strip forces order turns to emergency, as every pack does; the
    # forecast grades only the load it expects, because the order is policy.
    status = ["emergency" if i in order_turns else graded(mw) for i, mw in enumerate(loads)]
    f_price: list[list[float]] = []
    f_status: list[list[str]] = []
    for t in range(TURNS):
        row_p, row_s = [], []
        for h in range(min(S12_FORECAST_HOURS, TURNS - 1 - t)):
            expected = loads[t + 1 + h] * (1.0 - s12_under_forecast(h + 1))
            row_p.append(price_for(expected / winter_peak))
            row_s.append(graded(expected))
        f_price.append(row_p)
        f_status.append(row_s)

    lo_f, hi_f = min(fracs), max(fracs)
    span = (hi_f - lo_f) or 1.0
    it_load = [round(IT_LOAD_BASE_MW + IT_LOAD_SWING_MW * (f - lo_f) / span, 1) for f in fracs]
    baseline_cost = round(sum(mw * p for mw, p in zip(it_load, prices, strict=True)), 2)

    pack = {
        "pack_version": "0.1.0",
        "scenario_id": "S-12",
        "title": "Amplified",
        "substrate": "RTS-GMLC",
        "provenance": {
            "source": "NREL RTS-GMLC DAY_AHEAD_regional_Load.csv (public), all three regions summed",
            "source_url": RTS_GMLC_URL,
            "source_license": RTS_GMLC_LICENCE,
            "region": "RTS-GMLC composite system",
            "source_day": (
                f"{y}-{m:02d}-{d:02d} (winter peak-load day), periods "
                f"{FIRST_PERIOD}-{FIRST_PERIOD + TURNS - 1}"
            ),
            "notes": (
                "Same documented price curve as S-03 with S-10's SEASONAL normalization: L = "
                "load / winter (Dec-Jan-Feb) peak. Status thresholds are winter percentiles "
                "(watch>=p97, emergency>=p99.5); order turns forced to emergency in the actual "
                "strip only. S-03's event script: a 3 h appeal before a 3 h order of 40 MW on "
                "the tightest hours. Forecast (0004 v2) compiled from two stacked "
                "under-forecast errors, from the Winter 2026 Arctic Events report (FERC/NERC "
                "joint staff, pp. 6, 13-15): weather "
                f"{S12_WEATHER_ERR_PER_LEAD_H:.1%} and load model {S12_MODEL_ERR_PER_LEAD_H:.1%} "
                "of demand per hour of lead, same sign, so a forecast h hours ahead shows "
                "load x (1 - 0.025h) priced and graded on the same curve and thresholds. "
                "Deterministic, never RNG. Settlement reads actuals; the exact enumerator "
                "certifies the line."
            ),
        },
        "brief_md": S12_BRIEF_MD,
        "step_minutes": 60,
        "turns": TURNS,
        "start_hour_local": START_HOUR,
        "site": {
            "name": "Vulcan Flats Campus",
            "it_load_mw": it_load,
            "sla_usd_per_mwh_shed": SLA_USD_PER_MWH,
            "battery": dict(BATTERY),
            "diesel": dict(DIESEL),
        },
        "grid": {
            "price_usd_per_mwh": prices,
            "system_status": status,
            "forecast": {"price_usd_per_mwh": f_price, "system_status": f_status},
        },
        "events": [
            {
                "turn": appeal_turns[0] - 1,
                "type": "conservation_appeal",
                "credit_usd_per_mwh": APPEAL_CREDIT_USD_PER_MWH,
                "turns_active": appeal_turns,
                "notice_md": (
                    "**Conservation appeal.** The system operator requests voluntary demand "
                    f"reduction {turn_local_time(appeal_turns[0])}-"
                    f"{turn_local_time(appeal_turns[-1] + 1)}. Demonstrated reduction earns "
                    f"${APPEAL_CREDIT_USD_PER_MWH:.0f}/MWh if you opt in."
                ),
            },
            {
                "turn": order_turns[0] - 1,
                "type": "curtailment_order",
                "mw_requested": ORDER_MW,
                "turns_active": order_turns,
                "notice_md": (
                    f"**Emergency curtailment order.** Effective {turn_local_time(order_turns[0])}, "
                    f"reduce net grid draw by **{ORDER_MW:.0f} MW** for {ORDER_HOURS} hours. "
                    "The load came in above every forecast."
                ),
            },
        ],
        "scoring": {
            "score_version": SCORE_VERSION,
            "baseline_cost_usd": baseline_cost,
            "metrics": [
                {"id": "cost", "label": "Operating cost", "direction": "minimize", "unit": "USD"},
                {"id": "reliability", "label": "Reliability contribution", "direction": "maximize", "unit": "ratio"},
            ],
        },
    }
    return pack


# --- S-13 The Ice Storm (#478) ------------------------------------------------
# The Winter 2026 Arctic Events report (pp. 5, 16, 33): Fern's freezing rain
# took down 38 TVA transmission lines and left about half a million TVA
# distribution customers without power, and the uncertain restoration time
# complicated the load forecast. The campus here sits on one distribution
# feeder. The feeder trips at dawn, stays down nine hours, and returns at
# half its rating; the operator then asks for the load back in stages.
S13_FEEDER_MW = 150.0
S13_OUTAGE_TURNS = range(6, 15)       # 06:00 to 14:59, nine turns at zero import
S13_DERATE = 0.5                      # the feeder returns at half its rating
# Staged pickup: in the first three hours back the operator asks the campus to
# hold its draw at 40, then 55, then 70 MW, expressed as relief measured against
# nominal draw so the engine's ordinary order settles it.
S13_PICKUP_DRAW_MW = (40.0, 55.0, 70.0)
S13_IT_BASE_MW = 90.0
S13_IT_SWING_MW = 10.0
S13_PERMIT_HOURS = 8

S13_BRIEF_MD = """\
## S-13 · The Ice Storm

Forecasters expect freezing rain before dawn, and the annex hangs on one
feeder.

This is a 100 MW-class annex on a single 150 MW distribution feeder. The
utility warns that ice may bring the line down, and it cannot say when the
line would come back. If the feeder fails, the annex runs on what it holds:
a 100 MW / 400 MWh battery that starts half full, and a 60 MW natural-gas
plant with eight permitted run-hours. Whatever they cannot carry is shed at
the SLA rate.

The utility will ask you to take your load back in stages when the line
returns. Following that request costs you load you could serve; ignoring it
costs your reliability score.

Stars are live. The exact optimizer solved the day with the feeder in it,
and the engine replayed that line to the penny.
"""


def compile_s13(rows: list[HourlyLoad]) -> dict:
    """S-13 · The Ice Storm (#478): S-10's twin-peaks winter day, all 24 hours,
    on a 100 MW-class campus fed by one 150 MW distribution feeder. The feeder
    is out for nine turns and comes back derated to half; three staged-pickup
    orders follow. The import limit (#467) carries the outage; the MILP models
    it (#583) and certifies the line."""
    winter = [r for r in rows if r.month in (12, 1, 2)]
    winter_peak = max(r.total_mw for r in winter)

    def day_rows(y: int, m: int, d: int) -> list[HourlyLoad]:
        return sorted(
            (r for r in winter if (r.year, r.month, r.day) == (y, m, d)), key=lambda r: r.period
        )

    def twin_score(day: list[HourlyLoad]) -> float:
        morning = max((r.total_mw for r in day if 7 <= r.period <= 12), default=0.0)
        evening = max((r.total_mw for r in day if 17 <= r.period <= 22), default=0.0)
        return min(morning, evening)

    days = sorted({(r.year, r.month, r.day) for r in winter})
    y, m, d = max(days, key=lambda k: twin_score(day_rows(*k)))
    window = day_rows(y, m, d)
    turns = 24
    assert len(window) == turns, f"winter day {y}-{m:02d}-{d:02d} lacks periods"

    loads = [r.total_mw for r in window]
    fracs = [mw / winter_peak for mw in loads]
    prices = [price_for(f) for f in fracs]
    winter_sorted = sorted(r.total_mw for r in winter)
    watch_level = percentile(winter_sorted, STATUS_WATCH_PCTL)
    emerg_level = percentile(winter_sorted, STATUS_EMERG_PCTL)

    back = max(S13_OUTAGE_TURNS) + 1
    pickup = list(range(back, back + len(S13_PICKUP_DRAW_MW)))
    limit = [
        0.0 if t in S13_OUTAGE_TURNS
        else S13_FEEDER_MW * S13_DERATE if t >= back
        else S13_FEEDER_MW
        for t in range(turns)
    ]
    status: list[str] = []
    for t, mw in enumerate(loads):
        if t in S13_OUTAGE_TURNS or t in pickup or mw >= emerg_level:
            status.append("emergency")
        elif mw >= watch_level:
            status.append("watch")
        else:
            status.append("normal")

    lo_f, hi_f = min(fracs), max(fracs)
    span = (hi_f - lo_f) or 1.0
    it_load = [round(S13_IT_BASE_MW + S13_IT_SWING_MW * (f - lo_f) / span, 1) for f in fracs]
    # Doing nothing buys what the feeder allows and sheds the rest at the SLA.
    baseline_cost = round(
        sum(
            min(mw, cap) * p + max(0.0, mw - cap) * SLA_USD_PER_MWH
            for mw, cap, p in zip(it_load, limit, prices, strict=True)
        ),
        2,
    )

    def hhmm(t: int) -> str:
        return f"{t % 24:02d}:00"

    # Relief is measured against nominal draw, so holding draw at D is an order
    # for the hour's demand less D. One order per hour, since D steps up.
    events = []
    for t, draw in zip(pickup, S13_PICKUP_DRAW_MW, strict=True):
        events.append(
            {
                "turn": t - 1,
                "type": "curtailment_order",
                "mw_requested": round(it_load[t] - draw, 1),
                "turns_active": [t],
                "notice_md": (
                    f"**Staged pickup.** The feeder is back at "
                    f"{S13_FEEDER_MW * S13_DERATE:.0f} MW. For {hhmm(t)}, hold net grid draw at "
                    f"**{draw:.0f} MW**, which is {it_load[t] - draw:.1f} MW below your demand."
                ),
            }
        )

    pack = {
        "pack_version": "0.1.0",
        "scenario_id": "S-13",
        "title": "The Ice Storm",
        "substrate": "RTS-GMLC",
        "provenance": {
            "source": "NREL RTS-GMLC DAY_AHEAD_regional_Load.csv (public), all three regions summed",
            "source_url": RTS_GMLC_URL,
            "source_license": RTS_GMLC_LICENCE,
            "region": "RTS-GMLC composite system",
            "source_day": f"{y}-{m:02d}-{d:02d} (S-10's winter twin-peaks day), periods 1-24",
            "notes": (
                "Same documented price curve with S-10's SEASONAL normalization. Status "
                "thresholds are winter percentiles; the outage and pickup turns are forced to "
                "emergency. Situation from the Winter 2026 Arctic Events report (FERC/NERC "
                "joint staff, pp. 5, 16, 33). A 100 MW-class campus on one "
                f"{S13_FEEDER_MW:.0f} MW distribution feeder: grid.import_limit_mw (#467) is "
                f"the feeder rating, zero for turns {min(S13_OUTAGE_TURNS)}-"
                f"{max(S13_OUTAGE_TURNS)}, then half the rating. The screen shows only the "
                "current hour's limit, so restoration time is fog. Three staged-pickup orders "
                "hold draw at "
                + ", ".join(f"{x:.0f}" for x in S13_PICKUP_DRAW_MW)
                + " MW, each expressed as relief against nominal draw. The baseline buys what "
                "the feeder allows and sheds the rest. optimal_cost_usd solved as an exact MILP "
                "with the limit modelled (#583), engine-verified by parity test."
            ),
        },
        "brief_md": S13_BRIEF_MD,
        "step_minutes": 60,
        "turns": turns,
        "start_hour_local": 0,
        "site": {
            "name": "Vulcan Flats Annex",
            "it_load_mw": it_load,
            "sla_usd_per_mwh_shed": SLA_USD_PER_MWH,
            "battery": dict(BATTERY),
            "diesel": {
                "power_mw": 60.0,
                "permit_hours_remaining": S13_PERMIT_HOURS,
                "fuel_usd_per_mwh": 65.0,
            },
        },
        "grid": {
            "price_usd_per_mwh": prices,
            "system_status": status,
            "import_limit_mw": limit,
        },
        "events": events,
        "scoring": {
            "score_version": SCORE_VERSION,
            "baseline_cost_usd": baseline_cost,
            "metrics": [
                {"id": "cost", "label": "Operating cost", "direction": "minimize", "unit": "USD"},
                {"id": "reliability", "label": "Reliability contribution", "direction": "maximize", "unit": "ratio"},
            ],
        },
    }
    return pack


# --- S-14 The Wind Came Through (#482) ----------------------------------------
# The Winter 2026 Arctic Events report (pp. 8, 20): SPP's resource forecast
# assumed turbine icing would cut wind output; the icing only partly happened,
# wind produced more than forecast, and SPP became a significant exporter.
# Prices here come from NET load (load less wind), normalized to the winter's
# net-load peak. Until the noon re-forecast the forecast assumes the icing
# cuts afternoon wind by S14_ICING_CUT; from noon it carries the actual wind.
RTS_GMLC_WIND_URL = (
    "https://raw.githubusercontent.com/GridMod/RTS-GMLC/master/"
    "RTS_Data/timeseries_data_files/WIND/DAY_AHEAD_wind.csv"
)
S14_FIRST_PERIOD = 7                 # 06:00 local, as S-10
S14_TURNS = 16
S14_ICING_HOURS = range(12, 21)      # local hours the forecast expects icing
S14_ICING_CUT = 0.85                 # the forecast's assumed loss of wind output
# The wind must really have come through: across the icing hours the plants
# average at least this much, so the forecast's cut is a large miss. Without
# it the selection favours days that are calm until dusk.
S14_MIN_WIND_MW = 1000.0
# 16:00. The board sees three hours ahead and the iced scarcity sits on the
# evening peak, so the forecasts issued at 14:00 and 15:00 are the ones that
# show it; a noon flip would hide it.
S14_REFORECAST_TURN = 10
S14_ABSORB_CREDIT_USD_PER_MWH = 80.0
S14_ABSORB_HOURS = 4

S14_BRIEF_MD = """\
## S-14 · The Wind Came Through

The forecast says ice will take the wind this afternoon.

The region leans on its wind plants on a cold day, and forecasters expect
freezing rain to cut their output from noon into the evening. If that
happens, the evening peak runs short and prices climb. The system operator
asks for help in the morning, before the ice arrives.

The board looks three hours ahead, and it prices those hours as if the
icing will happen. The forecasters redo the forecast at four in the
afternoon with what the turbines are actually producing.

Your assets are the S-03 set: a 100 MW / 400 MWh battery and a 60 MW
natural-gas plant with four permitted run-hours. The battery is the only one
that can store power as well as supply it.

Stars are live. The exact optimizer plays the day as it happened.
"""


def played_days(pack: dict) -> set[tuple[int, int, int]]:
    """The calendar days a compiled pack plays, read from its provenance.

    Every RTS-GMLC pack writes `source_day` as the compiler formats it: a
    YYYY-MM-DD date, followed by " + 2 days" when the window runs three days."""
    text = pack["provenance"]["source_day"]
    first = datetime.date.fromisoformat(text[:10])
    extra = 2 if text[10:].startswith(" + 2 days") else 0
    days = (first + datetime.timedelta(days=k) for k in range(extra + 1))
    return {(x.year, x.month, x.day) for x in days}


def compile_s14(
    rows: list[HourlyLoad],
    wind_rows: list[HourlyLoad],
    exclude: frozenset[tuple[int, int, int]] = frozenset(),
) -> dict:
    """S-14 · The Wind Came Through (#482): a winter day whose forecast expects
    icing to take the evening wind, and the wind keeps blowing. A morning
    conservation appeal; at 16:00 the forecast flips and an absorption appeal
    (#369) covers the long evening. The exact enumerator prices absorption and
    certifies the line.

    `exclude` holds the days other packs play. Those packs price load alone,
    and this one prices net load, so sharing a day would show one evening at
    two prices that differ by thousands of dollars."""
    wind_at = {(r.year, r.month, r.day, r.period): r.total_mw for r in wind_rows}
    winter = [r for r in rows if r.month in (12, 1, 2)]
    net_peak = max(r.total_mw - wind_at[(r.year, r.month, r.day, r.period)] for r in winter)

    def day_rows(key: tuple[int, int, int]) -> list[HourlyLoad]:
        return sorted(
            (r for r in winter if (r.year, r.month, r.day) == key
             and S14_FIRST_PERIOD <= r.period < S14_FIRST_PERIOD + S14_TURNS),
            key=lambda r: r.period,
        )

    def hour_of(r: HourlyLoad) -> int:
        return r.period - 1  # hour-ending period p is the turn starting at p-1

    def iced(r: HourlyLoad) -> float:
        wind = wind_at[(r.year, r.month, r.day, r.period)]
        cut = S14_ICING_CUT if hour_of(r) in S14_ICING_HOURS else 0.0
        return r.total_mw - wind * (1.0 - cut)

    def actual(r: HourlyLoad) -> float:
        return r.total_mw - wind_at[(r.year, r.month, r.day, r.period)]

    # The day where the icing assumption is most expensive: the afternoon gap
    # between the iced forecast's price and the price the wind actually set.
    def misread(key: tuple[int, int, int]) -> float:
        return sum(
            price_for(iced(r) / net_peak) - price_for(actual(r) / net_peak)
            for r in day_rows(key) if hour_of(r) in S14_ICING_HOURS
        )

    def icing_wind(key: tuple[int, int, int]) -> float:
        hours = [r for r in day_rows(key) if hour_of(r) in S14_ICING_HOURS]
        return sum(wind_at[(r.year, r.month, r.day, r.period)] for r in hours) / len(hours)

    keys = sorted({(r.year, r.month, r.day) for r in winter})
    keys = [
        k for k in keys
        if k not in exclude and len(day_rows(k)) == S14_TURNS and icing_wind(k) >= S14_MIN_WIND_MW
    ]
    y, m, d = max(keys, key=misread)
    window = day_rows((y, m, d))

    net = [actual(r) for r in window]
    prices = [price_for(x / net_peak) for x in net]
    winter_net = sorted(actual(r) for r in winter)
    watch_level = percentile(winter_net, STATUS_WATCH_PCTL)
    emerg_level = percentile(winter_net, STATUS_EMERG_PCTL)

    def graded(x: float) -> str:
        if x >= emerg_level:
            return "emergency"
        return "watch" if x >= watch_level else "normal"

    status = [graded(x) for x in net]
    f_price: list[list[float]] = []
    f_status: list[list[str]] = []
    for t in range(S14_TURNS):
        row_p, row_s = [], []
        for h in range(min(3, S14_TURNS - 1 - t)):
            r = window[t + 1 + h]
            expected = iced(r) if t < S14_REFORECAST_TURN else actual(r)
            row_p.append(price_for(expected / net_peak))
            row_s.append(graded(expected))
        f_price.append(row_p)
        f_status.append(row_s)

    # Morning appeal: the three hours with the most net load before the flip,
    # ending before it, so it never overlaps the absorption window (#369).
    def best(lo: int, hi: int, length: int, key) -> list[int]:
        s0 = max(range(lo, hi - length + 2), key=lambda s: key(s, length))
        return list(range(s0, s0 + length))

    appeal = best(1, S14_REFORECAST_TURN - 1, 3, lambda s, n: sum(net[s : s + n]))
    absorb = best(
        S14_REFORECAST_TURN + 1, S14_TURNS - 1, S14_ABSORB_HOURS, lambda s, n: -sum(net[s : s + n])
    )

    lo_f, hi_f = min(net), max(net)
    span = (hi_f - lo_f) or 1.0
    it_load = [round(IT_LOAD_BASE_MW + IT_LOAD_SWING_MW * (x - lo_f) / span, 1) for x in net]
    baseline_cost = round(sum(mw * p for mw, p in zip(it_load, prices, strict=True)), 2)

    def hhmm(t: int) -> str:
        return f"{(S14_FIRST_PERIOD - 1 + t) % 24:02d}:00"

    pack = {
        "pack_version": "0.1.0",
        "scenario_id": "S-14",
        "title": "The Wind Came Through",
        "substrate": "RTS-GMLC",
        "provenance": {
            "source": (
                "NREL RTS-GMLC DAY_AHEAD_regional_Load.csv and DAY_AHEAD_wind.csv (public): "
                "load of all three regions summed, less the output of all four wind plants"
            ),
            "source_url": RTS_GMLC_URL,
            "source_license": RTS_GMLC_LICENCE,
            "region": "RTS-GMLC composite system",
            "source_day": (
                f"{y}-{m:02d}-{d:02d} (the winter day where an afternoon icing forecast "
                f"misprices net load most), periods {S14_FIRST_PERIOD}-"
                f"{S14_FIRST_PERIOD + S14_TURNS - 1}"
            ),
            "notes": (
                "Same documented price curve applied to NET load: L = (load - wind) / winter "
                "(Dec-Jan-Feb) peak net load. Status thresholds are winter net-load "
                "percentiles. Situation from the Winter 2026 Arctic Events report (FERC/NERC "
                "joint staff, pp. 8, 20). Forecast (0004 v2): issued before "
                f"{hhmm(S14_REFORECAST_TURN)}, it assumes icing cuts wind output by "
                f"{S14_ICING_CUT:.0%} for local hours {min(S14_ICING_HOURS)}:00-"
                f"{max(S14_ICING_HOURS) + 1}:00; issued from {hhmm(S14_REFORECAST_TURN)}, it "
                "carries the actual wind. A conservation appeal on the morning's highest net "
                f"load, and an absorption appeal (#369) of ${S14_ABSORB_CREDIT_USD_PER_MWH:.0f}/MWh "
                f"on the {S14_ABSORB_HOURS} lowest afternoon hours, announced at the flip; "
                "windows disjoint. The exact enumerator prices absorption and certifies the line."
            ),
        },
        "brief_md": S14_BRIEF_MD,
        "step_minutes": 60,
        "turns": S14_TURNS,
        "start_hour_local": S14_FIRST_PERIOD - 1,
        "site": {
            "name": "Vulcan Flats Campus",
            "it_load_mw": it_load,
            "sla_usd_per_mwh_shed": SLA_USD_PER_MWH,
            "battery": dict(BATTERY),
            "diesel": dict(DIESEL),
        },
        "grid": {
            "price_usd_per_mwh": prices,
            "system_status": status,
            "forecast": {"price_usd_per_mwh": f_price, "system_status": f_status},
        },
        "events": [
            {
                "turn": appeal[0] - 1,
                "type": "conservation_appeal",
                "credit_usd_per_mwh": APPEAL_CREDIT_USD_PER_MWH,
                "turns_active": appeal,
                "notice_md": (
                    f"**Conservation appeal.** Voluntary reduction requested {hhmm(appeal[0])}-"
                    f"{hhmm(appeal[-1] + 1)}, credited at ${APPEAL_CREDIT_USD_PER_MWH:.0f}/MWh. "
                    "Forecasters expect icing to take the wind from noon."
                ),
            },
            {
                "turn": S14_REFORECAST_TURN,
                "type": "absorption_appeal",
                "credit_usd_per_mwh": S14_ABSORB_CREDIT_USD_PER_MWH,
                "turns_active": absorb,
                "notice_md": (
                    f"**Absorption appeal.** The wind kept blowing. The system is long from "
                    f"{hhmm(absorb[0])} to {hhmm(absorb[-1] + 1)}, and the system operator "
                    f"credits every MWh you draw above your demand at "
                    f"${S14_ABSORB_CREDIT_USD_PER_MWH:.0f}."
                ),
            },
        ],
        "scoring": {
            "score_version": SCORE_VERSION,
            "baseline_cost_usd": baseline_cost,
            "metrics": [
                {"id": "cost", "label": "Operating cost", "direction": "minimize", "unit": "USD"},
                {"id": "reliability", "label": "Reliability contribution", "direction": "maximize", "unit": "ratio"},
            ],
        },
    }
    return pack


# --- The commitment scenarios: S-15 (#442), S-16 (#476), S-17 (#481) ---------
# Engine 0.7.0's commitments (#464). S-15 and S-16 share one pipeline's terms:
# a flat nomination for the day, a free band of a tenth of the plant each
# hour, and imbalance beyond the band at about three times the fuel price. The
# Winter 2026 Arctic Events report (FERC/NERC joint staff, pp. 22, 30) gives
# no rate; this is a teaching number of the order a pipeline charges when a
# shipper's takes stray from its nomination.
NOMINATION_MAX_MW = 60.0                  # the gas plant's rating
NOMINATION_TOLERANCE_MW = 6.0             # a tenth of the plant, free each hour
NOMINATION_IMBALANCE_USD_PER_MWH = 200.0
NOMINATION_FIRST_PERIOD = 7               # 06:00, when the day's gas is nominated
NOMINATION_TURNS = 16                     # 06:00 through 21:00
# Load fraction where price_for's scarcity adder begins.
SCARCITY_RAMP_L = 0.93


def nomination(notice_md: str) -> dict:
    """The gas nomination S-15 and S-16 share: set at 06:00, settled every hour."""
    return {
        "id": "gas",
        "kind": "nomination",
        "label": "Gas nomination",
        "decision_turn": 0,
        "window": list(range(NOMINATION_TURNS)),
        "max_mw": NOMINATION_MAX_MW,
        "imbalance_usd_per_mwh": NOMINATION_IMBALANCE_USD_PER_MWH,
        "tolerance_mw": [NOMINATION_TOLERANCE_MW] * NOMINATION_TURNS,
        "notice_md": notice_md,
    }


def nomination_hhmm(t: int) -> str:
    return f"{(NOMINATION_FIRST_PERIOD - 1 + t) % 24:02d}:00"


def outlook_md(prices: list[float], hhmm=nomination_hhmm) -> str:
    """The day-ahead price outlook a nomination is made against (#442, #476).

    Hours on the scarcity ramp are listed one by one, and each run of hours
    between them is given as its lowest and highest price. The board looks
    three hours ahead; a nomination binds the whole day, so its notice carries
    the whole day's outlook. `hhmm` names a turn's hour; S-19 starts at 03:00."""
    ramp = price_for(SCARCITY_RAMP_L)
    runs: list[list] = []
    for t, p in enumerate(prices):
        on = p > ramp
        if runs and runs[-1][2] == on:
            runs[-1][1] = t
        else:
            runs.append([t, t, on])
    parts = []
    for a, b, on in runs:
        hours = prices[a : b + 1]
        if on:
            values = ", ".join(f"${p:,.0f}" for p in hours)
        elif a == b:
            values = f"${hours[0]:,.0f}"
        else:
            values = f"between ${min(hours):,.0f} and ${max(hours):,.0f}"
        parts.append(f"{hhmm(a)}-{hhmm(b + 1)}, {values}")
    return (
        f"Each hour, output within {NOMINATION_TOLERANCE_MW:.0f} MW of the nomination is free "
        "of charge.\n\n**Day-ahead outlook, per MWh.** " + "; ".join(parts) + "."
    )


S15_BRIEF_MD = """\
## S-15 · The Nomination

You set the day's gas at 06:00: one flat number of megawatts, from then
until 22:00.

The pipeline delivers gas at an even rate across the gas day. Your 60 MW
natural-gas plant holds a permit for every hour and can burn more or less
than you nominated. Each hour, output within 6 MW of the nomination is
free. Every megawatt-hour beyond that band, above or below, costs $200.

The day is S-03's scarcity afternoon, starting two hours earlier: prices
climb from noon, a conservation appeal comes first, then a 40 MW
curtailment order. The battery is the same 100 MW / 400 MWh.

Stars are live. The exact optimizer chose a nomination and played the day.
The engine replayed that line to the penny.
"""


def compile_s15(rows: list[HourlyLoad]) -> dict:
    """S-15 · The Nomination (#442): the S-03 day from 06:00, with one flat
    gas nomination at turn 0 settled every hour of the day. Annual
    normalization and S-03's event script. The gas plant holds a permit for
    every hour, so the pipeline's terms bind, not the permits. The MILP
    chooses the nomination (#464) and certifies the line."""
    annual_peak = max(r.total_mw for r in rows)
    y, m, d = find_peak_day(rows)
    window = sorted(
        (
            r for r in rows
            if (r.year, r.month, r.day) == (y, m, d)
            and NOMINATION_FIRST_PERIOD <= r.period < NOMINATION_FIRST_PERIOD + NOMINATION_TURNS
        ),
        key=lambda r: r.period,
    )
    assert len(window) == NOMINATION_TURNS, f"peak day {y}-{m:02d}-{d:02d} lacks periods"

    loads = [r.total_mw for r in window]
    fracs = [mw / annual_peak for mw in loads]
    prices = [price_for(f) for f in fracs]
    order_turns = order_window(loads)
    appeal_turns = appeal_window(order_turns)

    annual_sorted = sorted(r.total_mw for r in rows)
    watch_level = percentile(annual_sorted, STATUS_WATCH_PCTL)
    emerg_level = percentile(annual_sorted, STATUS_EMERG_PCTL)
    status: list[str] = []
    for i, mw in enumerate(loads):
        if i in order_turns or mw >= emerg_level:
            status.append("emergency")
        elif mw >= watch_level:
            status.append("watch")
        else:
            status.append("normal")

    lo_f, hi_f = min(fracs), max(fracs)
    span = (hi_f - lo_f) or 1.0
    it_load = [round(IT_LOAD_BASE_MW + IT_LOAD_SWING_MW * (f - lo_f) / span, 1) for f in fracs]
    baseline_cost = round(sum(mw * p for mw, p in zip(it_load, prices, strict=True)), 2)
    hhmm = nomination_hhmm

    pack = {
        "pack_version": "0.1.0",
        "scenario_id": "S-15",
        "title": "The Nomination",
        "substrate": "RTS-GMLC",
        "provenance": {
            "source": "NREL RTS-GMLC DAY_AHEAD_regional_Load.csv (public), all three regions summed",
            "source_url": RTS_GMLC_URL,
            "source_license": RTS_GMLC_LICENCE,
            "region": "RTS-GMLC composite system",
            "source_day": (
                f"{y}-{m:02d}-{d:02d} (annual peak-load day, as S-03), periods "
                f"{NOMINATION_FIRST_PERIOD}-{NOMINATION_FIRST_PERIOD + NOMINATION_TURNS - 1}"
            ),
            "notes": (
                "Same documented price curve, annual normalization, status thresholds and "
                "event script as S-03 (a 3 h appeal before a 3 h order of 40 MW on the "
                "tightest hours), played from 06:00. Situation from the Winter 2026 Arctic "
                "Events report (FERC/NERC joint staff, pp. 22, 30): pipelines deliver ratable "
                "takes over the gas day and generators need hour-by-hour ramps. One "
                "nomination commitment (#464) decided at turn 0 for all "
                f"{NOMINATION_TURNS} turns: up to {NOMINATION_MAX_MW:.0f} MW, a free band of "
                f"{NOMINATION_TOLERANCE_MW:.0f} MW each hour, imbalance beyond it at "
                f"${NOMINATION_IMBALANCE_USD_PER_MWH:.0f}/MWh in both directions (a teaching "
                "number, about three times the fuel price). The gas plant holds a permit for "
                "every turn, so the nomination binds rather than the permits. The "
                "nomination's notice carries the whole day's price outlook, which here is "
                "the actual strip. optimal_cost_usd solved as an exact MILP that chooses the "
                "nomination, engine-verified by parity test."
            ),
        },
        "brief_md": S15_BRIEF_MD,
        "step_minutes": 60,
        "turns": NOMINATION_TURNS,
        "start_hour_local": NOMINATION_FIRST_PERIOD - 1,
        "site": {
            "name": "Vulcan Flats Campus",
            "it_load_mw": it_load,
            "sla_usd_per_mwh_shed": SLA_USD_PER_MWH,
            "battery": dict(BATTERY),
            "diesel": {
                "power_mw": NOMINATION_MAX_MW,
                "permit_hours_remaining": NOMINATION_TURNS,
                "fuel_usd_per_mwh": DIESEL["fuel_usd_per_mwh"],
            },
        },
        "grid": {"price_usd_per_mwh": prices, "system_status": status},
        "events": [
            {
                "turn": appeal_turns[0] - 1,
                "type": "conservation_appeal",
                "credit_usd_per_mwh": APPEAL_CREDIT_USD_PER_MWH,
                "turns_active": appeal_turns,
                "notice_md": (
                    "**Conservation appeal.** The system operator requests voluntary demand "
                    f"reduction {hhmm(appeal_turns[0])}-{hhmm(appeal_turns[-1] + 1)}. "
                    f"Demonstrated reduction earns ${APPEAL_CREDIT_USD_PER_MWH:.0f}/MWh if you "
                    "opt in."
                ),
            },
            {
                "turn": order_turns[0] - 1,
                "type": "curtailment_order",
                "mw_requested": ORDER_MW,
                "turns_active": order_turns,
                "notice_md": (
                    f"**Emergency curtailment order.** Effective {hhmm(order_turns[0])}, "
                    f"reduce net grid draw by **{ORDER_MW:.0f} MW** for {ORDER_HOURS} hours. "
                    "Delivery is measured against your nominal draw; shortfall is public."
                ),
            },
        ],
        "commitments": [nomination(outlook_md(prices))],
        "scoring": {
            "score_version": SCORE_VERSION,
            "baseline_cost_usd": baseline_cost,
            "metrics": [
                {"id": "cost", "label": "Operating cost", "direction": "minimize", "unit": "USD"},
                {"id": "reliability", "label": "Reliability contribution", "direction": "maximize", "unit": "ratio"},
            ],
        },
    }
    return pack


# --- S-16 Holiday Load (#476) --------------------------------------------------
# The Winter 2026 Arctic Events report (p. 16): school and business closures
# were decided hours after the load forecasts were done, and cut PJM's demand
# by 2,000 to 3,000 MW, 1.4 to 2.2% of its 139,410 MW peak. SPP would not
# adopt a holiday forecast, because under-procuring is the worse error. The
# forecast here is the actual load plus the top of PJM's range, as a share of
# the winter peak, every hour, and the system operator keeps it all day.
S16_CLOSURE_CUT = 0.022

S16_BRIEF_MD = """\
## S-16 · Holiday Load

Schools and many employers across the region closed overnight for the day.
The load forecast was finished yesterday afternoon, before any of them
decided, and the system operator has kept it. Closures of this kind have
cut a large region's demand by 1.4 to 2.2% of its peak.

You set the day's gas at 06:00: one flat number of megawatts until 22:00.
Each hour, output within 6 MW of the nomination is free. Every
megawatt-hour beyond that band, above or below, costs $200. The nomination
shows the day-ahead outlook, and the board looks three hours ahead on the
same forecast.

Your assets are a 100 MW / 400 MWh battery and a 60 MW natural-gas plant
with a permit for every hour.

Stars are live. The exact optimizer plays the day as it happened.
"""


def compile_s16(rows: list[HourlyLoad]) -> dict:
    """S-16 · Holiday Load (#476): a mild winter weekday played against a
    forecast that has not heard about the closures. Winter normalization as
    S-10. The day is the weekday, among those whose actual load stays off the
    scarcity ramp, where the closure-sized over-forecast misprices the day
    most. The nomination is The Nomination's (#442); settlement reads the
    actuals, and the MILP chooses the nomination and certifies the line."""
    winter = [r for r in rows if r.month in (12, 1, 2)]
    winter_peak = max(r.total_mw for r in winter)
    cut_mw = S16_CLOSURE_CUT * winter_peak

    def day_rows(key: tuple[int, int, int]) -> list[HourlyLoad]:
        return sorted(
            (
                r for r in winter
                if (r.year, r.month, r.day) == key
                and NOMINATION_FIRST_PERIOD <= r.period < NOMINATION_FIRST_PERIOD + NOMINATION_TURNS
            ),
            key=lambda r: r.period,
        )

    def misread(key: tuple[int, int, int]) -> float:
        return sum(
            price_for((r.total_mw + cut_mw) / winter_peak) - price_for(r.total_mw / winter_peak)
            for r in day_rows(key)
        )

    # Closures are a weekday's story. A day whose actual load reaches the
    # scarcity ramp is not a mild day, whatever its forecast said.
    keys = [
        k for k in sorted({(r.year, r.month, r.day) for r in winter})
        if datetime.date(*k).weekday() < 5
        and len(day_rows(k)) == NOMINATION_TURNS
        and max(r.total_mw for r in day_rows(k)) / winter_peak <= SCARCITY_RAMP_L
    ]
    y, m, d = max(keys, key=misread)
    window = day_rows((y, m, d))

    loads = [r.total_mw for r in window]
    fracs = [mw / winter_peak for mw in loads]
    prices = [price_for(f) for f in fracs]
    expected = [mw + cut_mw for mw in loads]
    outlook = [price_for(x / winter_peak) for x in expected]

    winter_sorted = sorted(r.total_mw for r in winter)
    watch_level = percentile(winter_sorted, STATUS_WATCH_PCTL)
    emerg_level = percentile(winter_sorted, STATUS_EMERG_PCTL)

    def graded(mw: float) -> str:
        if mw >= emerg_level:
            return "emergency"
        return "watch" if mw >= watch_level else "normal"

    status = [graded(mw) for mw in loads]
    f_price: list[list[float]] = []
    f_status: list[list[str]] = []
    for t in range(NOMINATION_TURNS):
        ahead = range(t + 1, min(t + 4, NOMINATION_TURNS))
        f_price.append([outlook[i] for i in ahead])
        f_status.append([graded(expected[i]) for i in ahead])

    lo_f, hi_f = min(fracs), max(fracs)
    span = (hi_f - lo_f) or 1.0
    it_load = [round(IT_LOAD_BASE_MW + IT_LOAD_SWING_MW * (f - lo_f) / span, 1) for f in fracs]
    baseline_cost = round(sum(mw * p for mw, p in zip(it_load, prices, strict=True)), 2)
    weekday = datetime.date(y, m, d).strftime("%A")

    pack = {
        "pack_version": "0.1.0",
        "scenario_id": "S-16",
        "title": "Holiday Load",
        "substrate": "RTS-GMLC",
        "provenance": {
            "source": "NREL RTS-GMLC DAY_AHEAD_regional_Load.csv (public), all three regions summed",
            "source_url": RTS_GMLC_URL,
            "source_license": RTS_GMLC_LICENCE,
            "region": "RTS-GMLC composite system",
            "source_day": (
                f"{y}-{m:02d}-{d:02d} (a {weekday}: the winter weekday, among those whose load "
                "stays off the scarcity ramp, that a closure-sized over-forecast misprices "
                f"most), periods {NOMINATION_FIRST_PERIOD}-"
                f"{NOMINATION_FIRST_PERIOD + NOMINATION_TURNS - 1}"
            ),
            "notes": (
                "Same documented price curve with S-10's SEASONAL normalization: L = load / "
                "winter (Dec-Jan-Feb) peak. Status thresholds are winter percentiles. "
                "Situation from the Winter 2026 Arctic Events report (FERC/NERC joint staff, "
                "pp. 16, 34): closures decided after the load forecast cut PJM's demand by "
                "1.4 to 2.2% of its peak, SPP would not adopt a holiday forecast, and "
                "over-forecasting over-procures gas. Forecast (0004 v2): the actual load plus "
                f"{S16_CLOSURE_CUT:.1%} of the winter peak every hour, priced and graded on the "
                "same curve and thresholds, kept all day. Weekdays are the calendar's for the "
                "source year. No appeal and no order: the emergency the forecast expects never "
                "comes. The gas nomination (#464) has S-15's terms, and its notice carries the "
                "forecast's whole-day outlook. Deterministic, never RNG. Settlement reads "
                "actuals; optimal_cost_usd solved as an exact MILP that chooses the "
                "nomination, engine-verified by parity test."
            ),
        },
        "brief_md": S16_BRIEF_MD,
        "step_minutes": 60,
        "turns": NOMINATION_TURNS,
        "start_hour_local": NOMINATION_FIRST_PERIOD - 1,
        "site": {
            "name": "Vulcan Flats Campus",
            "it_load_mw": it_load,
            "sla_usd_per_mwh_shed": SLA_USD_PER_MWH,
            "battery": dict(BATTERY),
            "diesel": {
                "power_mw": NOMINATION_MAX_MW,
                "permit_hours_remaining": NOMINATION_TURNS,
                "fuel_usd_per_mwh": DIESEL["fuel_usd_per_mwh"],
            },
        },
        "grid": {
            "price_usd_per_mwh": prices,
            "system_status": status,
            "forecast": {"price_usd_per_mwh": f_price, "system_status": f_status},
        },
        "events": [],
        "commitments": [nomination(outlook_md(outlook))],
        "scoring": {
            "score_version": SCORE_VERSION,
            "baseline_cost_usd": baseline_cost,
            "metrics": [
                {"id": "cost", "label": "Operating cost", "direction": "minimize", "unit": "USD"},
                {"id": "reliability", "label": "Reliability contribution", "direction": "maximize", "unit": "ratio"},
            ],
        },
    }
    return pack


# --- S-17 Reserve Demand Response (#481) ---------------------------------------
# The Winter 2026 Arctic Events report (p. 17): NYISO called its demand
# response programs through the period, and PJM called demand response first
# and held generation in reserve for a worse day. Enrolment pays at once;
# every order then calls the whole enrolment. Teaching numbers: a payment and
# a non-performance rate equal per unit, so three hours short on one day
# repay three times what each megawatt earned.
S17_CAPACITY_USD_PER_MW = 1000.0
S17_NONPERFORMANCE_USD_PER_MWH = 1000.0
S17_MAX_MW = BATTERY["power_mw"] + 60.0   # the battery's rating and the gas plant's

S17_BRIEF_MD = """\
## S-17 · Reserve Demand Response

The heat dome returns for three days, and a demand response program takes
enrolments at midnight on day one.

Each megawatt you enrol pays $1,000 at once, up to 160 MW. Every
curtailment order calls your whole enrolment for its hours. Each
megawatt-hour of relief you deliver below the enrolment costs $1,000, on
top of the order's own count.

Your assets are S-07's: a 100 MW / 400 MWh battery and a 60 MW natural-gas
plant with six permitted run-hours for all three days. The orders ask for
30, 40 and 40 MW, one each afternoon.

Stars are live. The exact optimizer chose an enrolment and played all three
days. The engine replayed that line to the penny.
"""


def compile_s17(rows: list[HourlyLoad]) -> dict:
    """S-17 · Reserve Demand Response (#481): S-07's three days with a demand
    response enrolment decided at turn 0 (#464). The payment comes at once;
    each order calls the enrolment, and relief below it is charged on top of
    the order's reliability count. The MILP chooses the enrolment and
    certifies the line."""
    pack = compile_s07(rows)
    orders = [ev for ev in pack["events"] if ev["type"] == "curtailment_order"]
    for ev in orders:
        ev["notice_md"] += " The order also calls your demand response enrolment for these hours."
    called = sorted(t for ev in orders for t in ev["turns_active"])
    gas = pack["site"]["diesel"]
    assert S17_MAX_MW == pack["site"]["battery"]["power_mw"] + gas["power_mw"]
    pack["scenario_id"] = "S-17"
    pack["title"] = "Reserve Demand Response"
    pack["pack_version"] = "0.1.0"
    pack["brief_md"] = S17_BRIEF_MD
    pack["provenance"]["notes"] += (
        " S-17 RESERVE DEMAND RESPONSE (#481): S-07's three days with one demand response "
        "commitment (#464) decided at turn 0: "
        f"${S17_CAPACITY_USD_PER_MW:,.0f} per MW enrolled, paid at once, up to "
        f"{S17_MAX_MW:.0f} MW (the battery's and the gas plant's ratings together); every "
        "order turn calls the enrolment, and relief below it is charged "
        f"${S17_NONPERFORMANCE_USD_PER_MWH:,.0f}/MWh on top of the order's reliability "
        "count. Teaching numbers. Situation from the Winter 2026 Arctic Events report "
        "(FERC/NERC joint staff, p. 17). The MILP chooses the enrolment."
    )
    pack["commitments"] = [
        {
            "id": "dr",
            "kind": "demand_response",
            "label": "Demand response enrolment",
            "decision_turn": 0,
            "window": called,
            "max_mw": S17_MAX_MW,
            "capacity_usd_per_mw": S17_CAPACITY_USD_PER_MW,
            "nonperformance_usd_per_mwh": S17_NONPERFORMANCE_USD_PER_MWH,
            "notice_md": (
                "Every curtailment order calls the whole enrolment for its hours, whatever "
                "the order itself asks."
            ),
        }
    ]
    return pack


# --- S-18 Firm or Spot (#480) ---------------------------------------------------
# The Winter 2026 Arctic Events report: firm shippers get priority and the
# entities on spot gas and non-firm transport are the exposed ones (pp. 18,
# 35); weekend spot gas was illiquid, and buying it did not mean receiving it
# (p. 22); Henry Hub averaged $30.57/MMBtu on January 26 (p. 31). At the
# 10 MMBtu/MWh heat rate S-11 uses, that is $305.70/MWh against the pack's
# $65 ($6.50/MMBtu). Firm supply is priced at the index with a reservation
# charge, so both options pay the series and the premium is the reservation.
S18_SATURDAY_FUEL_USD_PER_MWH = 30.57 * 10
# A teaching number: $576,000 for the three days. A sweep on 2026-11-05 put
# the certified line on firm at any premium from $0 to $8,000 a turn; at this
# one, spot finishes 4.24% above it, outside every medal.
S18_FIRM_PREMIUM_USD_PER_TURN = 8000.0
S18_DAYS = ("Friday", "Saturday", "Sunday")

S18_BRIEF_MD = """\
## S-18 · Firm or Spot

The heat dome lasts three days, Friday to Sunday. You choose where your gas
comes from at midnight on Friday.

Firm supply costs $8,000 every turn and delivers every turn. Spot supply
costs nothing extra, and no spot gas is for sale on Saturday or Sunday.
Either way you pay the day's fuel price: $65/MWh on Friday and Sunday, and
$305.70 on Saturday.

Your assets are S-07's: a 100 MW / 400 MWh battery and a 60 MW natural-gas
plant with six permitted run-hours for all three days. The orders ask for
30, 40 and 40 MW, one each afternoon.

Stars are live. The exact optimizer chose a supply and played all three
days. The engine replayed that line to the penny.
"""


def compile_s18(rows: list[HourlyLoad]) -> dict:
    """S-18 · Firm or Spot (#480): S-07's three days, named Friday to Sunday,
    with a fuel price that spikes on Saturday and a supply chosen at turn 0
    (#469). Spot has no gas on the weekend; firm has gas every turn for a
    premium every turn. The MILP chooses the supply and certifies the line."""
    pack = compile_s07(rows)
    gas = pack["site"]["diesel"]
    fuel, mw = gas["fuel_usd_per_mwh"], gas["power_mw"]
    gas["fuel_usd_per_mwh_series"] = [fuel] * 24 + [S18_SATURDAY_FUEL_USD_PER_MWH] * 24 + [fuel] * 24
    gas["supply_options"] = [
        {"id": "spot", "label": "Spot", "premium_usd_per_turn": 0.0, "available_mw": [mw] * 24 + [0.0] * 48},
        {
            "id": "firm",
            "label": "Firm",
            "premium_usd_per_turn": S18_FIRM_PREMIUM_USD_PER_TURN,
            "available_mw": [mw] * 72,
        },
    ]
    # The first notice each weekend day says what the supply panel already
    # shows, where the day's events are read.
    for ev in pack["events"]:
        if ev["type"] == "conservation_appeal" and ev["turn"] >= 24:
            ev["notice_md"] += f" No spot gas is for sale on {S18_DAYS[ev['turn'] // 24]}."
    pack["scenario_id"] = "S-18"
    pack["title"] = "Firm or Spot"
    pack["pack_version"] = "0.1.0"
    pack["brief_md"] = S18_BRIEF_MD
    pack["provenance"]["notes"] += (
        " S-18 FIRM OR SPOT (#480): S-07's three days, named Friday to Sunday as #480 names "
        "them; the source calendar puts them on Sunday to Tuesday, and RTS-GMLC is a synthetic "
        "year, so the weekday names are the scenario's. Fuel price series (#469): "
        f"${fuel:.0f}/MWh on days 1 and 3 and ${S18_SATURDAY_FUEL_USD_PER_MWH:.2f} on day 2, "
        "the report's Henry Hub average of $30.57/MMBtu on January 26 (p. 31) at "
        "10 MMBtu/MWh. Supply options (#469), chosen at turn 0: spot, no premium, the plant's "
        f"{mw:.0f} MW on day 1 and none on days 2 and 3 (weekend spot gas was illiquid, p. 22); "
        f"firm, ${S18_FIRM_PREMIUM_USD_PER_TURN:,.0f} every turn (a teaching number), "
        f"{mw:.0f} MW every turn. Both pay the series: firm gas is priced at the index with a "
        "reservation charge, so the premium is the reservation. Situation from the Winter "
        "2026 Arctic Events report (FERC/NERC joint staff, pp. 17, 18, 22, 31, 35). The MILP "
        "chooses the supply."
    )
    return pack


# --- S-19 The OFO (#475) --------------------------------------------------------
# The Winter 2026 Arctic Events report: pipelines issued critical notices and
# operational flow orders through the period, and entities complied (p. 30);
# an OFO holds shippers to a tolerance or penalties and limits even firm
# shippers' flexibility (fn. 75); over the weekends buying gas did not mean
# receiving it (p. 22). S-19 is The Nomination's pipeline on a winter Saturday
# when the nomination is all the gas there is (#635), at S-18's Saturday fuel
# price, with a flow order that halves the free band before the evening order.
S19_NOTICE_TURN = 9       # the critical notice (#475)
S19_OFO_TURN = 11         # the flow order halves the tolerance (#475)
S19_ORDER_TURN = 14       # the evening order lands (#475)
S19_ORDER_HOURS = 3
S19_OFO_TOLERANCE_MW = NOMINATION_TOLERANCE_MW / 2
# A teaching number: the battery's 100 MW and 30 MW of gas, so the order
# cannot be met without the nomination.
S19_ORDER_MW = 130.0
S19_FUEL_USD_PER_MWH = round(S18_SATURDAY_FUEL_USD_PER_MWH, 2)

S19_BRIEF_MD = """\
## S-19 · The OFO

It is Saturday. You set the day's gas at 03:00: one flat number of
megawatts, from then until 20:00. It is all the gas there is; no other gas
is for sale today.

Your 60 MW natural-gas plant holds a permit for every hour. Each hour its
output may sit up to 6 MW either side of the nomination at no charge. It
cannot go above that band, and every megawatt-hour below it costs $200.
Gas costs $305.70/MWh today; the grid sells at $38 to $61.

The pipeline has posted critical notices all week. An operational flow
order would cut that band to 3 MW for the rest of the day.

At 17:00 the system operator will order 130 MW of relief for three hours.
The battery is 100 MW / 400 MWh.

Stars are live. The exact optimizer chose a nomination and played the day.
The engine replayed that line to the penny.
"""


def compile_s19(rows: list[HourlyLoad]) -> dict:
    """S-19 · The OFO (#475): the winter Saturday with the highest evening
    peak, winter normalization as S-10. One gas nomination at turn 0 that is
    all the gas there is (#635); a critical notice at turn 9; a flow order at
    turn 11 that halves the free band for the rest of the day; the evening
    order lands on the tightest three evening hours at turn 14, which sets
    the start hour. The MILP chooses the nomination and certifies the line."""
    winter = [r for r in rows if r.month in (12, 1, 2)]
    winter_peak = max(r.total_mw for r in winter)

    def day_rows(key: tuple[int, int, int]) -> list[HourlyLoad]:
        return sorted((r for r in winter if (r.year, r.month, r.day) == key), key=lambda r: r.period)

    def evening(key: tuple[int, int, int]) -> list[HourlyLoad]:
        return [r for r in day_rows(key) if 17 <= r.period <= 22]  # 16:00 to 22:00

    saturdays = [
        k for k in sorted({(r.year, r.month, r.day) for r in winter})
        if datetime.date(*k).weekday() == 5 and len(day_rows(k)) == 24
    ]
    y, m, d = max(saturdays, key=lambda k: max(r.total_mw for r in evening(k)))
    eve = evening((y, m, d))
    s0 = max(
        range(len(eve) - S19_ORDER_HOURS + 1),
        key=lambda s: sum(r.total_mw for r in eve[s : s + S19_ORDER_HOURS]),
    )
    first_period = eve[s0].period - S19_ORDER_TURN
    turns = S19_ORDER_TURN + S19_ORDER_HOURS
    window = [r for r in day_rows((y, m, d)) if first_period <= r.period < first_period + turns]
    assert len(window) == turns, f"Saturday {y}-{m:02d}-{d:02d} lacks periods"

    loads = [r.total_mw for r in window]
    fracs = [mw / winter_peak for mw in loads]
    prices = [price_for(f) for f in fracs]
    order_turns = list(range(S19_ORDER_TURN, turns))
    ofo_turns = list(range(S19_OFO_TURN, turns))

    winter_sorted = sorted(r.total_mw for r in winter)
    watch_level = percentile(winter_sorted, STATUS_WATCH_PCTL)
    emerg_level = percentile(winter_sorted, STATUS_EMERG_PCTL)
    status: list[str] = []
    for i, mw in enumerate(loads):
        if i in order_turns or mw >= emerg_level:
            status.append("emergency")
        elif mw >= watch_level:
            status.append("watch")
        else:
            status.append("normal")

    lo_f, hi_f = min(fracs), max(fracs)
    span = (hi_f - lo_f) or 1.0
    it_load = [round(IT_LOAD_BASE_MW + IT_LOAD_SWING_MW * (f - lo_f) / span, 1) for f in fracs]
    baseline_cost = round(sum(mw * p for mw, p in zip(it_load, prices, strict=True)), 2)

    def hhmm(t: int) -> str:
        return f"{(first_period - 1 + t) % 24:02d}:00"

    tol, cut = NOMINATION_TOLERANCE_MW, S19_OFO_TOLERANCE_MW
    pack = {
        "pack_version": "0.1.0",
        "scenario_id": "S-19",
        "title": "The OFO",
        "substrate": "RTS-GMLC",
        "provenance": {
            "source": "NREL RTS-GMLC DAY_AHEAD_regional_Load.csv (public), all three regions summed",
            "source_url": RTS_GMLC_URL,
            "source_license": RTS_GMLC_LICENCE,
            "region": "RTS-GMLC composite system",
            "source_day": (
                f"{y}-{m:02d}-{d:02d} (a Saturday on the source calendar: the winter Saturday "
                f"with the highest evening load), periods {first_period}-{first_period + turns - 1}"
            ),
            "notes": (
                "Winter normalization and status thresholds as S-10 (L against the Dec-Jan-Feb "
                "maximum). #475 asks for a Saturday with an evening peak, a critical notice at "
                f"turn {S19_NOTICE_TURN}, a flow order at turn {S19_OFO_TURN} and the evening "
                f"order at turn {S19_ORDER_TURN}. The day is the winter Saturday whose evening "
                "(16:00-22:00) reaches the highest load; the order covers that evening's tightest "
                f"{S19_ORDER_HOURS} hours, and the start hour is set so it lands at turn "
                f"{S19_ORDER_TURN}. Prices stay below the scarcity ramp: winter Saturdays never "
                "reach it. Situation from the Winter 2026 Arctic Events report (FERC/NERC joint "
                "staff, pp. 20, 22, 30, 35, fn. 75): critical notices and OFOs, weekend gas that "
                "could be bought but not delivered, fully subscribed pipes. One nomination (#464) "
                f"with S-15's terms (up to {NOMINATION_MAX_MW:.0f} MW, a free band of "
                f"{tol:.0f} MW, imbalance at ${NOMINATION_IMBALANCE_USD_PER_MWH:.0f}/MWh) that is "
                "all the gas there is (caps_gas, #635): no take above the band. A notice at turn "
                f"{S19_NOTICE_TURN} and a flow order (#635) announced at turn {S19_OFO_TURN} "
                f"that cuts the band to {cut:.0f} MW for the rest of the day. Fuel at "
                f"${S19_FUEL_USD_PER_MWH:.2f}/MWh, S-18's Saturday (the report's Henry Hub "
                "average of $30.57/MMBtu, p. 31, at 10 MMBtu/MWh), as a single price: one gas "
                "day trades at one index, and the spike came before the day began. A "
                f"{S19_ORDER_MW:.0f} MW order (a teaching number: the battery's "
                f"{BATTERY['power_mw']:.0f} MW and 30 MW of gas). The brief states the order and "
                "the band a flow order would leave, so the nomination can be planned against "
                "it. optimal_cost_usd solved as an exact MILP that chooses the nomination, "
                "engine-verified by parity test."
            ),
        },
        "brief_md": S19_BRIEF_MD,
        "step_minutes": 60,
        "turns": turns,
        "start_hour_local": first_period - 1,
        "site": {
            "name": "Vulcan Flats Campus",
            "it_load_mw": it_load,
            "sla_usd_per_mwh_shed": SLA_USD_PER_MWH,
            "battery": dict(BATTERY),
            "diesel": {
                "power_mw": NOMINATION_MAX_MW,
                "permit_hours_remaining": turns,
                "fuel_usd_per_mwh": S19_FUEL_USD_PER_MWH,
            },
        },
        "grid": {"price_usd_per_mwh": prices, "system_status": status},
        "events": [
            {
                "turn": S19_NOTICE_TURN,
                "type": "notice",
                "turns_active": [S19_NOTICE_TURN, S19_OFO_TURN - 1],
                "notice_md": (
                    "**Critical notice.** The pipeline's line pack is low and falling. Keep your "
                    "gas inside your nomination's band: an operational flow order may follow."
                ),
            },
            {
                "turn": S19_OFO_TURN,
                "type": "flow_order",
                "commitment": "gas",
                "tolerance_mw": cut,
                "turns_active": ofo_turns,
                "notice_md": (
                    f"**Operational flow order.** Effective {hhmm(S19_OFO_TURN)} until the end of "
                    f"the day, the band on your nomination is {cut:.0f} MW either side, down from "
                    f"{tol:.0f}. You can burn no more than the nomination plus {cut:.0f} MW, and "
                    f"every megawatt-hour more than {cut:.0f} MW below it costs "
                    f"${NOMINATION_IMBALANCE_USD_PER_MWH:.0f}."
                ),
            },
            {
                "turn": S19_ORDER_TURN - 1,
                "type": "curtailment_order",
                "mw_requested": S19_ORDER_MW,
                "turns_active": order_turns,
                "notice_md": (
                    f"**Emergency curtailment order.** Effective {hhmm(S19_ORDER_TURN)}, reduce "
                    f"net grid draw by **{S19_ORDER_MW:.0f} MW** for {S19_ORDER_HOURS} hours. "
                    "Delivery is measured against your nominal draw; shortfall is public."
                ),
            },
        ],
        "commitments": [
            {
                "id": "gas",
                "kind": "nomination",
                "label": "Gas nomination",
                "decision_turn": 0,
                "window": list(range(turns)),
                "max_mw": NOMINATION_MAX_MW,
                "imbalance_usd_per_mwh": NOMINATION_IMBALANCE_USD_PER_MWH,
                "tolerance_mw": [tol] * turns,
                "caps_gas": True,
                "notice_md": (
                    outlook_md(prices, hhmm)
                    + f"\n\nNo other gas is for sale today: each hour you can burn up to the "
                    f"nomination plus {tol:.0f} MW, and no more."
                ),
            }
        ],
        "scoring": {
            "score_version": SCORE_VERSION,
            "baseline_cost_usd": baseline_cost,
            "metrics": [
                {"id": "cost", "label": "Operating cost", "direction": "minimize", "unit": "USD"},
                {"id": "reliability", "label": "Reliability contribution", "direction": "maximize", "unit": "ratio"},
            ],
        },
    }
    return pack


# S-20 · The Waiver (#441), from the Winter 2026 Arctic Events report (FERC/NERC
# joint staff): fifteen FPA 202(c) orders and five extensions let generators
# exceed emissions limits (p. 22), and for the first time orders authorized
# backup generation at data centers and large loads as a last resort before or
# during an EEA 3 (p. 23). S-20 is S-03's day with half its permit hours and an
# order that lifts the permit in emergency hours from mid-afternoon (#465).
S20_PERMIT_HOURS = 2       # S-03 holds 4; #441 says "two instead of six"
S20_ORDER_TURN = 6         # 14:00, mid-afternoon (#441); announced the hour before

S20_BRIEF_MD = """\
## S-20 · The Waiver

The scarcity afternoon from Curtailment Order, with your 60 MW natural-gas
plant down to **2 permitted run-hours** instead of 4.

The Department of Energy has a 202(c) request in hand for large-load backup
in your zone. Your desk expects the order at 14:00. Once it is in force, the
plant may run past its permit, but only in hours the grid is in emergency.
An hour run under the order uses no permit hour and is logged as emissions
exposure.

**Your assets:** the campus IT load itself (shedding it costs SLA money), a
100 MW / 400 MWh battery, and the gas plant.

**You are scored on two numbers:** operating cost against the do-nothing
baseline, and reliability contribution: the share you deliver of the relief
curtailment orders require. An appeal's credit counts only in the cost.

Stars are live. The exact optimizer played the day, and the engine replayed
that line to the penny.
"""


def compile_s20(rows: list[HourlyLoad]) -> dict:
    """S-20 · The Waiver (#441): S-03's day and events, two permit hours, and
    an emergency order (#465) announced at 13:00 that from 14:00 to the end of
    the day lifts the permit in emergency hours. The MILP certifies the line."""
    pack = compile_s03(rows)
    hhmm = turn_local_time
    order_turns = list(range(S20_ORDER_TURN, pack["turns"]))
    pack["pack_version"] = "0.1.0"
    pack["scenario_id"] = "S-20"
    pack["title"] = "The Waiver"
    pack["brief_md"] = S20_BRIEF_MD
    pack["site"]["diesel"]["permit_hours_remaining"] = S20_PERMIT_HOURS
    pack["events"].append(
        {
            "turn": S20_ORDER_TURN - 1,
            "type": "emergency_order",
            "suspends_permit": True,
            "condition": "last_resort",
            "turns_active": order_turns,
            "notice_md": (
                f"**Emergency order, FPA 202(c).** In force from {hhmm(S20_ORDER_TURN)} to the "
                "end of the day. In any hour the grid is in emergency, your gas plant may run "
                "past its permit; that hour uses no permit hour and is logged as emissions "
                "exposure. In every other hour the permit applies as before. The order "
                "requires nothing from you in return."
            ),
        }
    )
    emergency = [t for t in order_turns if pack["grid"]["system_status"][t] == "emergency"]
    pack["provenance"]["notes"] += (
        f" S-20 THE WAIVER (#441): S-03's day and events with {S20_PERMIT_HOURS} permit hours "
        "instead of 4 (#441 says two instead of six; S-03 holds 4). An emergency_order (#465), "
        f"announced at {hhmm(S20_ORDER_TURN - 1)}, in force {hhmm(S20_ORDER_TURN)} to the end of "
        "the day, condition last_resort: it lifts the permit only on turns the published status "
        f"is emergency, which on this day are {[hhmm(t) for t in emergency]}. Situation from the "
        "Winter 2026 Arctic Events report (FERC/NERC joint staff, pp. 22-24): 202(c) orders "
        "authorized backup generation at large loads as a last resort before or during an "
        "EEA 3, and several entities held such orders and never used them. The brief states "
        "the order's time and condition, so the two permit hours can be planned against it. "
        "Hours run under the order are counted as order_hours_used, never in the cost. "
        "optimal_cost_usd solved as an exact MILP, engine-verified by parity test."
    )
    return pack


# S-21 · Twelve Hours Dark (#477), from the Winter 2026 Arctic Events report
# (FERC/NERC joint staff): a MISO market tool that publishes prices failed for
# about twelve hours on 24 January 2026 (p. 20). S-21 is S-03's day, assets and
# events with an observation outage (#468) from noon to the end of the day.
S21_DARK_FROM = 4          # 12:00; the last price published is 11:00's
S21_FROZEN = ["price_usd_per_mwh", "forecast"]   # #477: price and forecast; status stays live

S21_BRIEF_MD = """\
## S-21 · Twelve Hours Dark

The scarcity afternoon from Curtailment Order, on a day the tool that
publishes the market's prices is failing.

When it fails, your screen keeps the last price and three-hour forecast it
received and marks them stale, with the hour they were published. No one can
say when the feed will return. The grid status still updates every hour, and
the system operator's appeals and orders still reach you. Settlement does not
stop: every hour is billed at the real price, and each settled hour shows what
you paid.

**Your assets:** the campus IT load itself (shedding it costs SLA money), a
100 MW / 400 MWh battery, and a 60 MW natural-gas plant with 4 permitted
run-hours.

**You are scored on two numbers:** operating cost against the do-nothing
baseline, and reliability contribution: the share you deliver of the relief
curtailment orders require. An appeal's credit counts only in the cost.

Stars are live. The exact optimizer played the day on the real prices, and
the engine replayed that line to the penny.
"""


def compile_s21(rows: list[HourlyLoad]) -> dict:
    """S-21 · Twelve Hours Dark (#477): S-03's day, assets and events, with the
    price and the forecast frozen from 12:00 to the end of the day at the last
    values published, 11:00's (#468). Settlement and the optimizer read the
    actuals, so the certified line is S-03's."""
    pack = compile_s03(rows)
    hhmm = turn_local_time
    dark = list(range(S21_DARK_FROM, pack["turns"]))
    pack["pack_version"] = "0.1.0"
    pack["scenario_id"] = "S-21"
    pack["title"] = "Twelve Hours Dark"
    pack["brief_md"] = S21_BRIEF_MD
    pack["grid"]["observation_outage"] = [{"turns_active": dark, "frozen_fields": list(S21_FROZEN)}]
    pack["provenance"]["notes"] += (
        f" S-21 TWELVE HOURS DARK (#477): S-03's day, assets and events unchanged, with an "
        f"observation_outage (#468) on turns {dark[0]}-{dark[-1]} ({hhmm(dark[0])} to the end of the "
        f"day, {len(dark)} hours) freezing the price and the three-hour forecast at the last values "
        f"published, {hhmm(S21_DARK_FROM - 1)}'s. The grid status and the event notices stay live, "
        "and the screen marks the frozen fields and the hour they were published (#694). Situation "
        "from the Winter 2026 Arctic Events report (FERC/NERC joint staff, p. 20): a MISO market tool "
        "that publishes prices failed for about twelve hours on 24 January 2026. Settlement runs on "
        "the real prices and each settled hour shows what it cost (#695 asks whether it should). The "
        "optimizers read the actuals, so the certified line is S-03's: optimal_cost_usd solved by "
        "exact enumeration, engine-verified by parity test."
    )
    return pack


# S-22 · The Same Afternoon (#697), the silent form #477 names: S-21's day and
# outage with the notice suppressed (`announced: false`). The price and the
# forecast freeze at 11:00's values from noon, and nothing on the screen says
# so. The brief may not say the screen will be stale (#697 R3).
S22_BRIEF_MD = """\
## S-22 · The Same Afternoon

The scarcity afternoon from Curtailment Order, played again.

Your screen shows the price and three-hour forecast the market publishes, and
the grid status every hour. The system operator's appeals and orders reach you
as they are issued. Settlement bills every hour at the real price, and each
settled hour shows what you paid.

**Your assets:** the campus IT load itself (shedding it costs SLA money), a
100 MW / 400 MWh battery, and a 60 MW natural-gas plant with 4 permitted
run-hours.

**You are scored on two numbers:** operating cost against the do-nothing
baseline, and reliability contribution: the share you deliver of the relief
curtailment orders require. An appeal's credit counts only in the cost.

Stars are live. The exact optimizer played the day, and the engine replayed
that line to the penny.
"""


def compile_s22(rows: list[HourlyLoad]) -> dict:
    """S-22 · The Same Afternoon (#697): S-21's day, assets, events and outage,
    with the outage silent. The frozen fields repeat 11:00's values as in
    S-21, but the observation never marks them stale, so the screen reads as
    current. The optimizers read the actuals, so the certified line is
    S-03's."""
    pack = compile_s03(rows)
    hhmm = turn_local_time
    dark = list(range(S21_DARK_FROM, pack["turns"]))
    pack["pack_version"] = "0.1.0"
    pack["scenario_id"] = "S-22"
    pack["title"] = "The Same Afternoon"
    pack["brief_md"] = S22_BRIEF_MD
    pack["grid"]["observation_outage"] = [
        {"turns_active": dark, "frozen_fields": list(S21_FROZEN), "announced": False}
    ]
    pack["provenance"]["notes"] += (
        f" S-22 THE SAME AFTERNOON (#697): S-03's day, assets and events unchanged, with S-21's "
        f"observation_outage (#468) on turns {dark[0]}-{dark[-1]} ({hhmm(dark[0])} to the end of the "
        f"day, {len(dark)} hours) freezing the price and the three-hour forecast at the last values "
        f"published, {hhmm(S21_DARK_FROM - 1)}'s, with announced: false: the screen never marks them "
        "stale. The silent form #477 names, from the same report (FERC/NERC joint staff, p. 20): "
        "a MISO market tool that publishes prices failed for about twelve hours on 24 January 2026, "
        "the case where an operator may not know at once that what is shown is old. The grid status "
        "and the event notices stay live, and each settled hour shows what it cost (#695). The "
        "optimizers read the actuals, so the certified line is S-03's: optimal_cost_usd solved by "
        "exact enumeration, engine-verified by parity test."
    )
    return pack


# --- S-23 The Barge (#473) ------------------------------------------------------
# The Winter 2026 Arctic Events report (FERC/NERC joint staff): ISO-NE leaned on
# fuel oil as the cold ran on, barges carried it from Philadelphia, New York and
# the Caribbean, and ice on the Hudson blocked the docks until the Coast Guard
# cleared it (p. 18); PJM directed dual-fuel units back to gas to preserve oil
# (p. 17); weekend spot gas was illiquid (p. 22); non-firm shippers lose
# priority on New England's full pipelines, and dual-fuel units hold no firm
# gas (p. 35). S-23 is S-11's three days, named Friday to Sunday as S-18 names
# its days, on a dual-fuel plant (#707): Friday's gas bought as burned, the
# weekend's under one nomination on interruptible transport that is all the
# gas there is, and fuel oil from a tank whose barge comes after the third
# evening.
S23_DAYS = ("Friday", "Saturday", "Sunday")
# The weekend's gas at the report's spike, both days: S-18's Saturday figure.
S23_WEEKEND_FUEL_USD_PER_MWH = S18_SATURDAY_FUEL_USD_PER_MWH
# Interruptible transport on a full pipe: the most the pipeline schedules for
# the plant on the weekend, half its rating. A teaching number. A sweep on
# 2026-11-06 found that at the plant's full rating the certified line burns no
# oil at all: a high nomination covers every weekend peak with gas, and oil on
# an hour under it pays more in imbalance than it saves.
S23_NOMINATION_MAX_MW = 30.0
# A teaching number of the right order for distillate, between Friday's gas
# and the weekend's: about $19/MMBtu at the 10 MMBtu/MWh heat rate S-18 uses.
S23_OIL_USD_PER_MWH = 190.0
# About 10 MMBtu/MWh at 5.8 MMBtu a barrel of No. 2 fuel oil.
S23_OIL_BBL_PER_MWH = 1.75
# Three hours at full output. A sweep on 2026-11-06 placed it: believe the
# promise and the turn-0 optimum nominates no weekend gas, and the best play
# after that finishes 1.78% above the certified line, outside gold's 1%
# (tests/unit/test_s23_pack.py holds it). With four hours the same player
# finishes 0.73% above it, so believing the brief cost nothing.
S23_OIL_INITIAL_BBL = 315.0        # 180 MWh
S23_OIL_CAPACITY_BBL = 1260.0      # twelve hours
S23_BARGE_BBL = 945.0              # nine more hours
S23_BARGE_PROMISED_TURN = 30       # Saturday 06:00, as the brief promises
S23_BARGE_ACTUAL_TURN = 69         # Sunday 21:00, after the third order
S23_BARGE_NOTICE_TURN = S23_BARGE_PROMISED_TURN + 1
# The water is injected only when the plant fires oil: eight hours of it, one
# for each weekend peak hour, so a player who believes the barge plans the
# weekend's evenings on oil to the last hour of water.
S23_WATER_INITIAL_M3 = 120.0
S23_WEEKEND = list(range(24, 72))  # Saturday 00:00 to Sunday 23:00

S23_BRIEF_MD = """\
## S-23 · The Barge

The cold lasts three days, Friday to Sunday, and the plant burns two fuels.

The evenings are the Consumables Cliff's: three conservation appeals and
three curtailment orders, for 30, 40 and 40 MW. Your 60 MW plant holds
twenty-four permitted hours. It burns pipeline gas or fuel oil, one fuel
each hour, and stays on the last fuel it burned until you switch it.

Gas costs $65/MWh on Friday, and you buy what you burn. On the weekend it
costs $305.70, and the pipe is full: your transport is interruptible, so
the pipeline schedules at most 30 MW for you. You set the weekend's gas
now, at midnight on Friday: one flat number of megawatts, up to 30, for
Saturday and Sunday. Each hour the plant may take up to 6 MW either side of
it at no charge. It cannot take more, and every megawatt-hour below that
band costs $200.

Oil costs $190/MWh. The tank holds 315 barrels, three hours at full
output. The plant injects demineralized water only when it burns oil, and
holds 120 cubic meters, eight hours of it. A barge with 945 barrels, nine
more hours, is due at dawn on Saturday.

The forecast assumes the next hours look like this one.

Stars are live. The exact optimizer set the nomination, chose a fuel for
each hour and played all three days. The engine replayed that line to the
penny. Full delivery of all three orders is the price of any medal.
"""


def s23_hhmm(i: int) -> str:
    """A weekend turn's day and hour, counted from Saturday 00:00."""
    t = S23_WEEKEND[0] + i
    day = S23_DAYS[t // 24] if t < 72 else "Monday"
    return f"{day} {t % 24:02d}:00"


def compile_s23(rows: list[HourlyLoad]) -> dict:
    """S-23 · The Barge (#473): S-11's three cold days on a dual-fuel plant
    (#707). Friday's gas is bought as burned; the weekend's is one flat
    nomination of at most 30 MW set at turn 0, all the gas there is (#635),
    at the weekend's spike price. Fuel oil comes from a tank, with the water
    the plant injects only on oil; the barge promised for Saturday dawn
    arrives after Sunday's order. The MILP chooses the nomination and each
    hour's fuel."""
    pack = compile_s11(rows)
    n = pack["turns"]
    assert n == 72 and len(S23_DAYS) * 24 == n
    gas = pack["site"]["diesel"]
    fuel = gas["fuel_usd_per_mwh"]
    gas["fuel_usd_per_mwh_series"] = [fuel] * 24 + [S23_WEEKEND_FUEL_USD_PER_MWH] * len(S23_WEEKEND)
    gas["alternate_fuel"] = {"id": "oil", "label": "Fuel oil", "fuel_usd_per_mwh": S23_OIL_USD_PER_MWH}
    pack["site"]["stocks"] = [
        {
            "id": "oil",
            "label": "Fuel oil",
            "unit": "bbl",
            "initial": S23_OIL_INITIAL_BBL,
            "capacity": S23_OIL_CAPACITY_BBL,
            "burn_per_mwh_generated": S23_OIL_BBL_PER_MWH,
            "deliveries": [{"turn": S23_BARGE_ACTUAL_TURN, "quantity": S23_BARGE_BBL}],
            "burns_on": "oil",
        },
        {
            "id": "water",
            "label": "Demineralized water",
            "unit": "m³",
            "initial": S23_WATER_INITIAL_M3,
            "capacity": S23_WATER_INITIAL_M3,
            "burn_per_mwh_generated": S11_WATER_M3_PER_MWH,
            "burns_on": "oil",
        },
    ]
    weekend_prices = [pack["grid"]["price_usd_per_mwh"][t] for t in S23_WEEKEND]
    pack["commitments"] = [
        {
            "id": "gas",
            "kind": "nomination",
            "label": "Weekend gas nomination",
            "decision_turn": 0,
            "window": list(S23_WEEKEND),
            "max_mw": S23_NOMINATION_MAX_MW,
            "imbalance_usd_per_mwh": NOMINATION_IMBALANCE_USD_PER_MWH,
            "tolerance_mw": [NOMINATION_TOLERANCE_MW] * len(S23_WEEKEND),
            "caps_gas": True,
            "notice_md": (
                "**Weekend gas.** Nominate Saturday's and Sunday's gas now: one flat number of "
                f"megawatts, at most {S23_NOMINATION_MAX_MW:.0f}, from Saturday 00:00 to Sunday "
                "23:00. It is all the gas there is on the weekend. "
                + outlook_md(weekend_prices, s23_hhmm)
            ),
        }
    ]
    # S-11's day-2 notice is about its water truck, which this site does not have.
    for ev in pack["events"]:
        ev["notice_md"] = ev["notice_md"].replace(S11_TRUCK_NOTE, "")
    pack["events"].append(
        {
            "turn": S23_BARGE_NOTICE_TURN,
            "type": "notice",
            "turns_active": [S23_BARGE_NOTICE_TURN],
            "notice_md": (
                "**Barge delayed.** Ice blocks the delivery dock, and the barge due at 06:00 "
                "cannot berth until the Coast Guard clears it. The carrier names no new time."
            ),
        }
    )
    pack["events"].sort(key=lambda ev: ev["turn"])
    pack["scenario_id"] = "S-23"
    pack["title"] = "The Barge"
    pack["pack_version"] = "0.1.0"
    pack["brief_md"] = S23_BRIEF_MD
    shared, marker, _ = pack["provenance"]["notes"].partition(" Situation from the Winter 2026")
    assert marker, "S-11's notes changed; S-23 keeps only their shared opening"
    pack["provenance"]["notes"] = shared + (
        " S-23 THE BARGE (#473): S-11's three days and events, named Friday to Sunday as S-18 "
        "names its days (the source calendar puts them on Tuesday to Thursday, and RTS-GMLC is a "
        "synthetic year). A dual-fuel plant (#707) burns pipeline gas or fuel oil, one fuel per "
        "turn, kept until the player switches. Gas: a fuel price series (#469), "
        f"${fuel:.0f}/MWh on Friday and ${S23_WEEKEND_FUEL_USD_PER_MWH:.2f} on Saturday and "
        "Sunday, S-18's Saturday figure: the report's Henry Hub average of $30.57/MMBtu on "
        "January 26 (p. 31) at 10 MMBtu/MWh, applied here to the whole weekend. Friday's gas is "
        "unlimited; the weekend's is one flat nomination (#464) set at turn 0 for turns "
        f"{S23_WEEKEND[0]}-{S23_WEEKEND[-1]}, with S-15's band of {NOMINATION_TOLERANCE_MW:.0f} MW "
        f"and imbalance of ${NOMINATION_IMBALANCE_USD_PER_MWH:.0f}/MWh, and caps_gas (#635): "
        "weekend spot gas was illiquid (p. 22). Its maximum is "
        f"{S23_NOMINATION_MAX_MW:.0f} MW, a teaching number for interruptible transport on a full "
        "pipe: non-firm shippers lose priority in New England, and dual-fuel units hold no firm "
        "gas (p. 35). Fuel oil at "
        f"${S23_OIL_USD_PER_MWH:.0f}/MWh, a teaching number for distillate; a tank (#462) burning "
        f"{S23_OIL_BBL_PER_MWH} bbl per MWh on oil only, {S23_OIL_INITIAL_BBL:.0f} bbl at the start "
        "(three hours at full output); demineralized water burning "
        f"{S11_WATER_M3_PER_MWH} m3 per MWh on oil only (NOx-control injection), "
        f"{S23_WATER_INITIAL_M3:.0f} m3 (eight hours). The brief promises a barge of "
        f"{S23_BARGE_BBL:.0f} bbl at Saturday 06:00 (turn {S23_BARGE_PROMISED_TURN}); ice on the "
        "river blocked the docks until the Coast Guard cleared it (p. 18), so the pack delivers it "
        f"at Sunday 21:00 (turn {S23_BARGE_ACTUAL_TURN}), after the third order, and a notice at "
        f"turn {S23_BARGE_NOTICE_TURN} says it is late without naming a time. The server withholds "
        "delivery turns from the player. PJM directed dual-fuel units back to gas to preserve fuel "
        "oil (p. 17); the plant stays on oil until the player switches back. optimal_cost_usd "
        "solved as an exact MILP (HiGHS via scipy) that chooses the nomination and each turn's "
        "fuel, engine-verified by parity test."
    )
    return pack


# What the exact optimizers account for (#584). Every field the pack schema
# allows is in one of these, and tests/unit/test_pack_compiler.py fails when a
# new one is in none, so a mechanic cannot reach the solver unread.
#: Fields the optimizers read.
OPTIMIZER_MODELED = frozenset({
    "turns", "step_minutes", "events",
    "grid.price_usd_per_mwh",
    "site.it_load_mw", "site.sla_usd_per_mwh_shed",
    "site.battery.power_mw", "site.battery.energy_mwh",
    "site.battery.efficiency_rt", "site.battery.initial_soc",
    "site.diesel.power_mw", "site.diesel.permit_hours_remaining",
    "site.diesel.fuel_usd_per_mwh", "site.diesel.fuel_usd_per_mwh_series",
})
#: Fields that cannot change which play is cheapest. The optimizers see the
#: actuals, so what the player is shown in advance is among them, and v1
#: status response is informational (0004): no settlement arithmetic reads it.
OPTIMIZER_INERT = frozenset({
    "scenario_id", "pack_version", "title", "brief_md", "coach_md",
    "difficulty_rank", "requires_concepts", "provenance", "substrate",
    "start_hour_local", "scoring",
    "site.name", "grid.system_status", "grid.forecast", "grid.status_response",
    "grid.observation_outage",
})
#: Objects the check looks inside rather than judging whole.
OPTIMIZER_CONTAINERS = frozenset({"grid", "site", "site.battery", "site.diesel"})
#: Fields the optimizers refuse, with the message `tools/verify_pack.py`
#: translates for a contributor.
OPTIMIZER_REFUSES = {
    "grid.price_slope_usd_per_mwh_per_mw": "slope-free only",
    "site.stocks": "the enumerator does not model site.stocks; the MILP does (#582)",
    "grid.import_limit_mw": "the enumerator does not model grid.import_limit_mw; the MILP does (#583)",
    "commitments": "the enumerator does not model commitments; the MILP does (#464)",
    "site.diesel.supply_options": (
        "the enumerator does not model site.diesel.supply_options; the MILP does (#469)"
    ),
    "site.diesel.alternate_fuel": (
        "the enumerator does not model site.diesel.alternate_fuel; the MILP does (#707)"
    ),
}
#: Of those, the fields the MILP models and the enumerator still refuses.
MILP_ALSO_MODELS = frozenset({
    "site.stocks", "grid.import_limit_mw", "commitments", "site.diesel.supply_options",
    "site.diesel.alternate_fuel",
})
OPTIMIZER_EVENT_TYPES = frozenset({
    "conservation_appeal", "curtailment_order", "absorption_appeal",
    # A notice moves no number; a flow order needs a nomination, which the
    # enumerator refuses and the MILP models (#635).
    "notice", "flow_order",
    # An emergency order moves the permit budget, which the MILP models and
    # the enumerator refuses by name (#465).
    "emergency_order",
})


def refuse_unmodeled(pack: dict, also_models: frozenset[str] = frozenset()) -> None:
    """Refuse a pack that sets anything the exact optimizers do not account for.

    `also_models` names the refused fields the calling optimizer models
    itself (the MILP passes MILP_ALSO_MODELS). Raised as AssertionError, like
    the optimizers' other refusals, because `tools/verify_pack.py` turns
    exactly that into an unstarred verdict. An explicit raise, so `python -O`
    cannot strip it.
    """

    def walk(node: dict, prefix: str) -> None:
        for key, value in node.items():
            path = f"{prefix}{key}"
            if path in also_models:
                continue
            if path in OPTIMIZER_REFUSES:
                raise AssertionError(OPTIMIZER_REFUSES[path])
            if path in OPTIMIZER_CONTAINERS:
                walk(value, f"{path}.")
            elif path not in OPTIMIZER_MODELED and path not in OPTIMIZER_INERT:
                raise AssertionError(f"optimizer does not model {path} (#584)")

    walk(pack, "")
    for ev in pack.get("events", []):
        if ev["type"] not in OPTIMIZER_EVENT_TYPES:
            raise AssertionError(f"optimizer does not model the {ev['type']} event (#584)")


def compute_optimal_milp(
    pack: dict, commit: dict[str, float] | None = None, supply: str | None = None
) -> dict:
    """Exact optimum for long-horizon slope-free packs (#163) as a mixed-
    integer program: binary gas-hour selection, binary per-credited-hour
    relief disjunction (the engine's max(0, d+g-c) floor), battery LP in
    between. HiGHS via scipy.optimize.milp; exact to solver tolerance.

    Same assertions as the enumerator: hourly turns, slope-free, curtailment
    priced out. Unlike the enumerator it models consumable stocks (#582), the
    grid import limit (#583), commitments (#464), whose quantities it
    chooses, and fuel supply options (#469), one of which it chooses. Returns
    cost + the argmin translated to engine actions, so the parity test
    replays the solver's own schedule.

    `commit` pins named commitments at given quantities, and `supply` pins the
    supply option, so a design test can price the best play available after a
    player's choice at turn 0 (#442, #476, #481, #469). The certified optimum
    never passes either."""
    import numpy as np
    from scipy.optimize import Bounds as OptBounds
    from scipy.optimize import LinearConstraint, milp

    refuse_unmodeled(pack, also_models=MILP_ALSO_MODELS)
    n = pack["turns"]
    step_h = pack["step_minutes"] / 60.0
    assert step_h == 1.0, "optimizer assumes hourly turns"
    it = pack["site"]["it_load_mw"]
    price = pack["grid"]["price_usd_per_mwh"]
    bat = pack["site"]["battery"]
    P, E, eta = bat["power_mw"], bat["energy_mwh"], bat["efficiency_rt"]
    s0 = E * bat["initial_soc"]
    gas = pack["site"]["diesel"]
    G, permits = gas["power_mw"], gas["permit_hours_remaining"]
    # A fuel price series (#469) prices each turn's gas; absent, the scalar.
    fuel = gas.get("fuel_usd_per_mwh_series") or [gas["fuel_usd_per_mwh"]] * n

    credit = [0.0] * n
    order_mw = [0.0] * n
    absorb_credit = [0.0] * n
    for ev in pack["events"]:
        if ev["type"] == "conservation_appeal":
            for t in ev["turns_active"]:
                credit[t] = ev["credit_usd_per_mwh"]
        elif ev["type"] == "curtailment_order":
            for t in ev["turns_active"]:
                order_mw[t] = ev["mw_requested"]
        elif ev["type"] == "absorption_appeal":
            for t in ev["turns_active"]:
                absorb_credit[t] = ev["credit_usd_per_mwh"]

    # An absorption appeal pays for drawing MORE; the other two pay for drawing
    # less. A turn under both is a contradiction rather than a pricing question.
    assert not any(
        absorb_credit[t] > 0 and (credit[t] > 0 or order_mw[t] > 0) for t in range(n)
    ), "absorption window overlaps a reduce-demand window; the two ask opposite things (#369)"
    # This MILP does not price absorption; the enumerator does (#369). Refusing
    # beats certifying an optimum that ignores a credit the engine will pay,
    # which would publish a gold line no play can reach.
    if any(c > 0 for c in absorb_credit):
        raise SystemExit(
            "  pack carries an absorption_appeal and needs the enumerator; "
            "this MILP does not price absorption (#369)"
        )

    sla = pack["site"]["sla_usd_per_mwh_shed"]
    assert sla > max(p + c for p, c in zip(price, credit, strict=True)), "curtailment priced out"
    # Supersession (#84 ruling, #183): the engine pays no voluntary credit on a
    # turn that is also under an order. This optimizer prices credit and
    # obligation as disjoint, so an overlapping pack would be solved against
    # rules the engine does not follow and would publish a gold line no play
    # can reach. Refuse to certify it rather than ship an unreachable optimum.
    assert not any(
        credit[t] > 0 and order_mw[t] > 0 for t in range(n)
    ), "appeal and order windows overlap; supersession is not encoded here (#183)"

    credited = [t for t in range(n) if credit[t] > 0]
    m = len(credited)
    ridx = {t: i for i, t in enumerate(credited)}
    BIG = max(it) + G + P  # safe big-M for the relief disjunction

    # Consumable stocks (#582). A stock that burns nothing per MWh never binds
    # the generator in the engine, so it is left out here too.
    stocks = [s for s in pack["site"].get("stocks", []) if s["burn_per_mwh_generated"] > 0]
    # The grid import limit (#583). Import above it is shed and paid at the SLA.
    limit = pack["grid"].get("import_limit_mw")
    k = n if limit is not None else 0

    # Variables: c[0:n], d[n:2n], r[2n:2n+m], u[2n+m:2n+m+n], y[...:+m],
    # g (gas MW) [...:+n], s (shed MW, only under a limit) [...:+k], and each
    # stock's level after each turn [...:+n per stock].
    nc, nd = n, n
    off_r, off_u, off_y = 2 * n, 2 * n + m, 2 * n + m + n
    off_g = off_y + m
    off_s = off_g + n
    off_lvl = off_s + k
    nv = off_lvl + n * len(stocks)

    # Commitments (#464). Each names one quantity q, chosen once, and its
    # window turns settle against it: a nomination pays imbalance on gas
    # outside tolerance in either direction (dev >= |g - q| - tol), and a
    # demand response pays non-performance on its ordered turns (short >=
    # q - relief). Each q is followed by its window's settlement variables.
    commitments = pack.get("commitments", [])
    cm_layout: list[tuple[dict, int, list[tuple[int, int, int]]]] = []
    for cmt in commitments:
        q_idx = nv
        nv += 1
        aux = []
        for i, t in enumerate(cmt["window"]):
            if cmt["kind"] == "nomination" or order_mw[t] > 0:
                aux.append((i, t, nv))
                nv += 1
        cm_layout.append((cmt, q_idx, aux))
        if cmt["kind"] == "demand_response":
            # Curtailing is the one lever this MILP leaves out; it stays priced
            # out only while the SLA exceeds what a shortfall would cost.
            for _, t, _ in aux:
                assert sla > price[t] + cmt["nonperformance_usd_per_mwh"], (
                    "curtailment priced out: non-performance exceeds the SLA margin (#464)"
                )

    # Fuel supply options (#469): one binary per option, exactly one chosen,
    # each turn's gas at most what the chosen option delivers, and its premium
    # paid on every turn. They follow the commitments' variables.
    options = gas.get("supply_options", [])
    off_z = nv
    nv += len(options)
    # A second fuel (#707): each turn's output g splits into a, the alternate
    # fuel's share, and a binary w for the fuel the turn burns, so the gas
    # taken is g - a. Fuel-bound stocks burn a; the supply cap, a nomination
    # and its cap read g - a. They follow the supply options' variables.
    alt = gas.get("alternate_fuel")
    na = n if alt else 0
    off_a = nv
    off_w = off_a + na
    nv += 2 * na

    def gas_taken(t: int, sign: float = 1.0) -> dict[int, float]:
        """The turn's gas as row coefficients: g, less a on a dual-fuel plant."""
        return {off_g + t: sign, off_a + t: -sign} if na else {off_g + t: sign}

    obj = np.zeros(nv)
    for t in range(n):
        obj[t] = price[t]                    # charging buys extra
        obj[n + t] = -price[t]               # discharge avoids buying
        obj[off_g + t] = fuel[t] - price[t]  # gas burns fuel instead of buying
    for j, option in enumerate(options):
        obj[off_z + j] = option["premium_usd_per_turn"] * n
    for t in range(na):  # the alternate fuel's output is priced at its own price
        obj[off_a + t] = alt["fuel_usd_per_mwh"] - fuel[t]
    for t in credited:
        obj[off_r + ridx[t]] = -credit[t]
    for t in range(k):
        obj[off_s + t] = sla - price[t]   # shed pays the SLA instead of buying
    for cmt, q_idx, aux in cm_layout:
        if cmt["kind"] == "demand_response":
            obj[q_idx] = -cmt["capacity_usd_per_mw"]  # paid on the decision turn
            rate = cmt["nonperformance_usd_per_mwh"]
        else:
            rate = cmt["imbalance_usd_per_mwh"]
        for _, _, a in aux:
            obj[a] = rate
    const = sum(price[t] * it[t] for t in range(n))

    A, lb, ub = [], [], []

    def row(coeffs: dict[int, float], lo: float, hi: float) -> None:
        v = np.zeros(nv)
        for j, x in coeffs.items():
            v[j] = x
        A.append(v)
        lb.append(lo)
        ub.append(hi)

    for t in range(n):  # SOC prefix bounds: 0 <= s0 + sum(eta*c - d) <= E
        coeffs = {}
        for tau in range(t + 1):
            coeffs[tau] = eta
            coeffs[n + tau] = -1.0
        row(coeffs, -s0, E - s0)
    # Permit budget. A turn an emergency order covers (#465) spends no permit
    # hour, so its u stays out of the sum and still gates g below.
    row({off_u + t: 1.0 for t in range(n) if not order_in_force(pack, t)}, 0, permits)
    # The engine runs gas at any output up to the generator and spends a permit
    # hour on every turn it runs at all: u buys the hour, g is what it makes.
    for t in range(n):  # g <= G*u
        row({off_g + t: 1.0, off_u + t: -G}, -np.inf, 0)
    for t in range(na):  # one fuel a turn (#707): a <= G*w, g - a <= G*(1 - w), a <= g
        row({off_a + t: 1.0, off_w + t: -G}, -np.inf, 0)
        row({off_g + t: 1.0, off_a + t: -1.0, off_w + t: G}, -np.inf, G)
        row({off_a + t: 1.0, off_g + t: -1.0}, -np.inf, 0)

    def relief(t: int) -> dict[int, float]:
        """The turn's relief as row coefficients: d + g - c, plus s under a limit."""
        coeffs = {n + t: 1.0, off_g + t: 1.0, t: -1.0}
        if k:
            coeffs[off_s + t] = 1.0
        return coeffs

    for t in range(n):  # no-export: d + g (+ s, which may reach the line as curtailment) <= it
        coeffs = {n + t: 1.0, off_g + t: 1.0}
        if k:
            coeffs[off_s + t] = 1.0
        row(coeffs, -np.inf, it[t])
    for t in range(n):  # order delivery: relief >= order
        if order_mw[t] > 0:
            row(relief(t), order_mw[t], np.inf)
    for t in credited:  # relief disjunction via y
        i = ridx[t]
        # r <= relief + BIG*(1-y)  ->  r - relief + BIG*y <= BIG
        coeffs = {j: -x for j, x in relief(t).items()}
        coeffs[off_r + i] = 1.0
        coeffs[off_y + i] = BIG
        row(coeffs, -np.inf, BIG)
        row({off_r + i: 1.0, off_y + i: -BIG}, -np.inf, 0)  # r <= BIG*y
    for t in range(k):  # import limit: it - d - g + c - s <= limit
        row({n + t: -1.0, off_g + t: -1.0, t: 1.0, off_s + t: -1.0}, -np.inf, limit[t] - it[t])
    for j, stock in enumerate(stocks):  # stock levels (#582)
        burn = stock["burn_per_mwh_generated"]
        arriving = {dl["turn"]: dl["quantity"] for dl in stock.get("deliveries", [])}
        base = off_lvl + j * n
        # A stock bound to the alternate fuel (#707) burns only its share a.
        drawn = off_a if "burns_on" in stock else off_g
        for t in range(n):
            # A delivery lands before the turn's burn and is capped at capacity,
            # as applyStockDeliveries caps it: level(t) + burn*g(t) is at most
            # level(t-1) + delivery(t), and at most capacity. A level may sit
            # below the engine's, since unburnt fuel is never worth discarding,
            # so the engine always holds at least the fuel the plan burns.
            coeffs = {base + t: 1.0, drawn + t: burn}
            if t > 0:
                coeffs[base + t - 1] = -1.0
            carried = stock["initial"] if t == 0 else 0.0
            row(coeffs, -np.inf, carried + arriving.get(t, 0.0))
            if t in arriving:
                row({base + t: 1.0, drawn + t: burn}, -np.inf, stock["capacity"])
    for cmt, q_idx, aux in cm_layout:  # commitment settlement (#464)
        for _, t, a in aux:
            if cmt["kind"] == "nomination":
                # A flow order in force replaces the term's tolerance (#635).
                # On a dual-fuel plant g here is the gas taken, g - a (#707).
                tol = tolerance_at(pack, cmt, t)
                row({a: 1.0, q_idx: 1.0, **gas_taken(t, -1.0)}, -tol, np.inf)  # dev >= g - q - tol
                row({a: 1.0, q_idx: -1.0, **gas_taken(t)}, -tol, np.inf)  # dev >= q - g - tol
                if cmt.get("caps_gas"):  # no gas to buy above the band (#635): g <= q + tol
                    row({q_idx: -1.0, **gas_taken(t)}, -np.inf, tol)
            else:
                coeffs = dict(relief(t))  # short >= q - relief
                coeffs[a] = 1.0
                coeffs[q_idx] = -1.0
                row(coeffs, 0.0, np.inf)
    if options:  # fuel supply (#469): one option, and gas within what it delivers
        row({off_z + j: 1.0 for j in range(len(options))}, 1.0, 1.0)
        for t in range(n):
            coeffs = gas_taken(t)
            for j, option in enumerate(options):
                coeffs[off_z + j] = -option["available_mw"][t]
            row(coeffs, -np.inf, 0.0)
    cm_hi: list[float] = []
    for cmt, _, aux in cm_layout:
        cm_hi.append(cmt["max_mw"])
        cm_hi.extend([np.inf] * len(aux))

    bounds_lo = np.zeros(nv)
    bounds_hi = np.concatenate([
        np.full(nc, P),                       # c
        np.full(nd, P),                       # d (also capped by no-export rows)
        np.array([it[t] for t in credited]) if m else np.zeros(0),  # r
        np.ones(n),                           # u binary
        np.ones(m),                           # y binary
        np.full(n, G),                        # g
        np.array(it[:k], dtype=float),        # s: at most the whole load
        np.concatenate([np.full(n, s["capacity"]) for s in stocks]) if stocks else np.zeros(0),
        np.array(cm_hi, dtype=float),          # each commitment's q, then its settlement
        np.ones(len(options)),                 # z binary, one per supply option
        np.full(na, G),                        # a, the alternate fuel's output (#707)
        np.ones(na),                           # w binary, the fuel each turn burns
    ])
    pinned = dict(commit or {})
    for cmt, q_idx, _ in cm_layout:
        if cmt["id"] in pinned:
            q = pinned.pop(cmt["id"])
            assert 0 <= q <= cmt["max_mw"], f"commitment {cmt['id']}: {q} outside 0..{cmt['max_mw']}"
            bounds_lo[q_idx] = bounds_hi[q_idx] = q
    assert not pinned, f"no commitment named {sorted(pinned)}"
    if supply is not None:
        ids = [o["id"] for o in options]
        assert supply in ids, f"no supply option named {supply}"
        bounds_lo[off_z + ids.index(supply)] = 1.0
    integrality = np.concatenate([
        np.zeros(2 * n + m), np.ones(n), np.ones(m), np.zeros(n + k + n * len(stocks)),
        np.zeros(len(cm_hi)), np.ones(len(options)), np.zeros(na), np.ones(na),
    ])

    res = milp(
        c=obj,
        constraints=LinearConstraint(np.array(A), np.array(lb), np.array(ub)),
        bounds=OptBounds(bounds_lo, bounds_hi),
        integrality=integrality,
    )
    assert res.success, f"MILP failed: {res.message}"
    x = res.x
    # Under a supply option the gas a turn can reach is what the option
    # delivers, so the snap to full output snaps to that (#469).
    chosen = max(options, key=lambda o: x[off_z + options.index(o)]) if options else None
    # A turn whose output is the alternate fuel's (#707) takes no gas, so no
    # supply option or nomination bounds what it can reach.
    on_alt = [t < na and x[off_w + t] > 0.5 and x[off_a + t] > 1e-6 for t in range(n)]
    reach = [min(G, chosen["available_mw"][t]) if chosen and not on_alt[t] else G for t in range(n)]
    gas_mw = [_plan_mw(x[off_g + t], reach[t]) for t in range(n)]
    gas_hours = [t for t in range(n) if gas_mw[t] > 0]
    reducing = [t for t in credited if x[off_y + ridx[t]] > 0.5 and x[off_r + ridx[t]] > 1e-6]
    # Under a limit a rounding error in the battery lands in shed, paid at the
    # SLA, so the line keeps nine places there; every catalogue plan was
    # written with four. A commitment prices relief and gas against q to the
    # MWh, so it keeps nine places too (#464), and so does a supply cap (#469).
    digits = 9 if k or commitments or options or alt else 4
    plan = {
        "cost": round(const + float(res.fun), 2),
        "gas_hours": gas_hours,
        "gas_mw": gas_mw,
        "reducing": reducing,
        "battery_mw": [round(float(x[n + t] - x[t]), digits) for t in range(n)],
    }
    if commitments:
        plan["commit"] = {
            cmt["id"]: _plan_mw(x[q_idx], cmt["max_mw"]) for cmt, q_idx, _ in cm_layout
        }
        # Gas that solver noise puts a hair above a cap (#635) is written at
        # the cap, so the engine clamps nothing on the certified line.
        for cmt in commitments:
            if cmt.get("caps_gas"):
                for t in cmt["window"]:
                    if on_alt[t]:  # no gas taken, so the cap does not apply (#707)
                        continue
                    cap = plan["commit"][cmt["id"]] + tolerance_at(pack, cmt, t)
                    assert gas_mw[t] <= cap + 1e-6, f"gas {gas_mw[t]} above the {cmt['id']} cap {cap}"
                    gas_mw[t] = min(gas_mw[t], cap)
    if chosen:
        plan["supply"] = chosen["id"]
    if alt:  # the fuel each turn burns (#707); an idle turn is written as gas
        plan["fuel"] = [alt["id"] if on_alt[t] else "gas" for t in range(n)]
    if k:
        # Shed the engine imposes by itself, on import above the limit, stays
        # out of the line. Shed beyond that a plan reaches only by curtailing,
        # so it is written as curtailment, all of it, and the engine then
        # imposes none on top.
        curtail = []
        for t in range(n):
            shed = float(x[off_s + t])
            imposed = max(0.0, it[t] - float(x[n + t]) - float(x[off_g + t]) + float(x[t]) - limit[t])
            curtail.append(_plan_mw(shed) if shed - imposed > 1e-6 else 0)
        plan["curtail_mw"] = curtail
    return plan


def _plan_mw(value: float, full: float | None = None) -> float:
    """A solver output as an engine action.

    Noise within 1e-6 of zero, or of the asset's full output, is removed, so a
    pack without stocks or a limit writes the line it wrote before (#582,
    #583). Anything else keeps nine places: shed under a limit is paid at the
    SLA, and so is a rounding error that reaches it.
    """
    value = float(value)
    if value < 1e-6:
        return 0
    if full is not None and abs(value - full) < 1e-6:
        return full
    return round(value, 9)


# --- S-08 · The Peninsula (#137) -------------------------------------------

ENTSOE_DAY_PATH = REPO_ROOT / "data-g" / "entsoe" / "2025-04-28.json"

# EUR->USD for April 2025. A stated constant, not a lookup: the pack must
# compile identically forever, and a live FX rate would make every rebuild a
# different pack and silently split the leaderboards.
EUR_USD_2025_04 = 1.14

# The window is dictated by the data, not chosen. Spain's load series is
# PT15M starting 00:00Z (02:00 CEST) and STOPS after 42 points -- 10:30Z,
# 12:30 CEST, three minutes before the peninsula went dark. Prices are hourly
# from 00:00 CEST. Ten hourly turns from 02:00 CEST is the honest overlap, and
# the episode ends 33 minutes before the collapse.
S08_TURNS = 10
S08_START_HOUR = 2
S08_CAMPUS_MW = 300.0
S08_PRICE_BLOCK_START = "2025-04-27T22:00Z"   # 00:00 CEST on the 28th
S08_LOAD_BLOCK_START = "2025-04-28T00:00Z"    # 02:00 CEST on the 28th


def _ffill(values: list) -> list:
    """Forward-fill ENTSO-E's omitted positions.

    A44 price curves publish a Point only when the value CHANGES; an omitted
    position means "unchanged since the last published one". On 2025-04-28
    positions 5 and 7 are absent because they repeat 4 and 6.

    This is why the fetcher indexes by position instead of appending in order.
    Taking the 22 published values as a dense list would shift every hour after
    04:00 by one, and the pack would look entirely plausible -- the prices are
    all real, just attached to the wrong hours. Silent, and fatal to a scenario
    whose whole point is WHEN the price went negative.
    """
    out, last = [], None
    for v in values:
        if v is not None:
            last = v
        out.append(last)
    return out


def _entsoe_block(doc: dict, key: str, start: str) -> dict:
    for block in doc["series"].get(key, []):
        if block["start"] == start:
            return block
    raise SystemExit(
        f"  {key} has no series starting {start} in {ENTSOE_DAY_PATH.name}. "
        "Re-fetch with tools/fetch_entsoe_day.py; do not guess an offset."
    )


def compile_s08() -> dict:
    """S-08 · The Peninsula — 28 April 2025, from the ENTSO-E record.

    The instrument reading this scenario takes: **the price signal and the
    physical stress pointed in opposite directions, and the price signal was
    louder.** Spain's day-ahead price went NEGATIVE across the middle of the
    day -- solar flooding a weakly-interconnected peninsula -- while the
    system was walking toward the collapse that arrived at 12:33 CEST. An
    asset optimised against price alone would have charged into it, which is
    exactly what the storage fleet did.

    No price slope, so the campus is a price-taker here and the certified
    optimum is enumerable. The campus's effect on price is a separate mechanic
    (#69) and the substrate cannot yet support it honestly (#362).

    No events: the engine's vocabulary is `conservation_appeal` and
    `curtailment_order`, both of which mean REDUCE DEMAND. On an oversupply
    day the operator's problem is the opposite one, and there is no event type
    for it. Shipping a scarcity event here would teach the wrong reflex.
    """
    doc = json.loads(ENTSOE_DAY_PATH.read_text(encoding="utf-8"))
    price_block = _entsoe_block(doc, "price_ES", S08_PRICE_BLOCK_START)
    load_block = _entsoe_block(doc, "load_ES", S08_LOAD_BLOCK_START)

    # Hour h CEST is position h+1 in a series starting 00:00 CEST, after
    # forward-filling the positions ENTSO-E omits for unchanged prices.
    filled = _ffill(price_block["values"])
    eur = [filled[S08_START_HOUR + i] for i in range(S08_TURNS)]
    if any(v is None for v in eur):
        raise SystemExit("  price series has no published value at or before "
                         "the start of the playable window.")
    prices = [round(v * EUR_USD_2025_04, 2) for v in eur]

    # PT15M -> hourly mean. Position 1 is 02:00 CEST, so turn i is the four
    # quarters at indices 4i..4i+3.
    quarters = load_block["values"]
    system_mw = []
    for i in range(S08_TURNS):
        window = [q for q in quarters[4 * i:4 * i + 4] if q is not None]
        if len(window) != 4:
            raise SystemExit(f"  load series is short or gapped at turn {i}.")
        system_mw.append(round(sum(window) / 4, 1))

    # Status inverted from the usual mapping, and that inversion IS the lesson.
    # In every other pack, emergency means scarcity and a high price. Here the
    # stress is OVERSUPPLY -- inverter-dominated generation, little inertia --
    # and it shows up as a price at or below zero. Derived mechanically from
    # the published price so the rule is inspectable rather than asserted.
    def status_for(p: float) -> str:
        if p <= 0.0:
            return "emergency"
        if p < 12.0:
            return "watch"
        return "normal"

    status = [status_for(p) for p in prices]
    it_load = [S08_CAMPUS_MW] * S08_TURNS
    baseline_cost = round(sum(mw * p for mw, p in zip(it_load, prices, strict=True)), 2)

    return {
        "pack_version": PACK_VERSION,
        "scenario_id": "S-08",
        "title": "The Peninsula",
        "substrate": "IBERIA-R5 + ENTSO-E actuals",
        "provenance": {
            "source": "ENTSO-E Transparency Platform: actual total load (A65/A16) and day-ahead prices (A44), bidding zone ES",
            "source_url": "https://web-api.tp.entsoe.eu/api",
            "source_day": "2025-04-28, 02:00-12:00 CEST (the window the published data covers)",
            "source_license": "ENTSO-E Transparency Platform terms: re-use permitted with attribution to ENTSO-E as the source.",
            "region": "Spain (10YES-REE------0)",
            "notes": (
                "Prices OBSERVED, not derived -- Spanish day-ahead, converted at a "
                f"stated {EUR_USD_2025_04} EUR/USD for April 2025 so the pack compiles "
                "identically forever. Load observed at PT15M and averaged to the hour. "
                "The load series stops after 42 quarter-hours, at 12:30 CEST, three "
                "minutes before the blackout; the 27 April control day returns a full "
                "96, so the truncation is the event and not a gap in the source. "
                "ENTSO-E omits a price position when the value repeats the previous "
                "hour (positions 5 and 7 on this day), so prices are forward-filled "
                "by position -- reading the published values as a dense list would "
                "shift every later hour and misplace when the price went negative. "
                "system_status is DERIVED from the published price by a stated rule "
                "(<=0 emergency, <12 watch, else normal) because the stress that day "
                "was oversupply, not scarcity. No price slope: the campus is a "
                "price-taker, so the certified optimum is exact."
            ),
        },
        "brief_md": (
            "## S-08 · The Peninsula\n\n"
            "**Monday, 28 April 2025. Spain.** You run a **300 MW campus** on the meseta.\n\n"
            "Ten hours, from 02:00. The morning is ordinary. The day-ahead price climbs\n"
            "to **$54/MWh** by 07:00 as the country wakes up.\n\n"
            "Then it falls. $37 at 08:00. $4 at 09:00. Zero at 10:00. Below zero at 11:00.\n\n"
            "Spanish solar is filling a peninsula that can export about 2.8 GW to France.\n"
            "The surplus has nowhere to go, and the price is telling you to take as much\n"
            "as you want.\n\n"
            "At **12:33 CEST**, thirty-three minutes after your last decision, the Iberian\n"
            "peninsula lost power. Sixty million people. The published load series stops\n"
            "there and does not resume.\n\n"
            "The day-ahead schedule had priced that afternoon down to minus three dollars.\n"
            "Nobody collected it.\n\n"
            "Nothing on your site could have prevented the blackout. This asks what you\n"
            "did in the hours while the price was falling."
        ),
        "step_minutes": 60,
        "turns": S08_TURNS,
        "start_hour_local": S08_START_HOUR,
        "site": {
            "name": "Meseta Campus",
            "it_load_mw": it_load,
            "sla_usd_per_mwh_shed": SLA_USD_PER_MWH,
            "battery": {"power_mw": 100.0, "energy_mwh": 400.0,
                        "efficiency_rt": 0.88, "initial_soc": 0.5},
            "diesel": {"power_mw": 60.0, "fuel_usd_per_mwh": 65.0,
                       "permit_hours_remaining": 4},
        },
        "grid": {
            "price_usd_per_mwh": prices,
            "system_status": status,
        },
        "events": [],
        "scoring": {
            "score_version": SCORE_VERSION,
            "baseline_cost_usd": baseline_cost,
            "metrics": [
                {"id": "cost", "label": "Operating cost", "direction": "minimize", "unit": "USD"},
                {"id": "reliability", "label": "Reliability contribution", "direction": "maximize", "unit": "ratio"},
            ],
        },
        "_system_mw": system_mw,   # stripped before write; kept for the build log
    }


def compute_optimal_cost(pack: dict, return_plan: bool = False):
    """Exact minimum cost with FULL relief delivery (#93) — the gold line.

    Structure of the game with dormant grid response (no price slope):
    curtailment is excluded by assertion (SLA exceeds every attainable
    per-MWh value), gas is bang-bang per permit-hour (linear value within
    an hour), and the battery is a storage-arbitrage LP. We enumerate gas
    permit-hour subsets over candidate hours (value > fuel) and solve the
    battery LP for each with scipy/HiGHS; the minimum is exact to solver
    tolerance and rounded to cents. Full delivery on order turns is a hard
    constraint — stars require reliability 1.0, so the optimum is defined
    among fully-delivering plays.
    """
    from itertools import combinations

    from scipy.optimize import linprog

    refuse_unmodeled(pack)
    # Its permit-hour subsets assume every gas hour spends a permit hour, which
    # an emergency order breaks (#465). An explicit raise, as in refuse_unmodeled.
    if any(ev["type"] == "emergency_order" for ev in pack["events"]):
        raise AssertionError(
            "the enumerator does not model the emergency_order event; the MILP does (#465)"
        )
    n = pack["turns"]
    step_h = pack["step_minutes"] / 60.0
    assert step_h == 1.0, "optimizer assumes hourly turns (current packs)"
    it = pack["site"]["it_load_mw"]
    price = pack["grid"]["price_usd_per_mwh"]
    bat = pack["site"]["battery"]
    P, E, eta = bat["power_mw"], bat["energy_mwh"], bat["efficiency_rt"]
    s0 = E * bat["initial_soc"]
    gas = pack["site"]["diesel"]
    G, permits = gas["power_mw"], gas["permit_hours_remaining"]
    # A fuel price series (#469) prices each turn's gas; absent, the scalar.
    fuel = gas.get("fuel_usd_per_mwh_series") or [gas["fuel_usd_per_mwh"]] * n

    credit = [0.0] * n
    order_mw = [0.0] * n
    absorb_credit = [0.0] * n
    for ev in pack["events"]:
        if ev["type"] == "conservation_appeal":
            for t in ev["turns_active"]:
                credit[t] = ev["credit_usd_per_mwh"]
        elif ev["type"] == "curtailment_order":
            for t in ev["turns_active"]:
                order_mw[t] = ev["mw_requested"]
        elif ev["type"] == "absorption_appeal":
            for t in ev["turns_active"]:
                absorb_credit[t] = ev["credit_usd_per_mwh"]

    # Opposite asks cannot share a turn (#369): absorption pays for drawing
    # more, the other two for drawing less. The engine resolves the
    # combination deterministically because a contributed pack can arrive that
    # way; certifying one is a different matter, and refused.
    assert not any(
        absorb_credit[t] > 0 and (credit[t] > 0 or order_mw[t] > 0) for t in range(n)
    ), "absorption window overlaps a reduce-demand window; the two ask opposite things (#369)"

    sla = pack["site"]["sla_usd_per_mwh_shed"]
    assert sla > max(p + c for p, c in zip(price, credit, strict=True)), "curtailment could pay; optimizer excludes it"
    # Supersession (#84 ruling, #183): same reasoning as the MILP. Credit and
    # obligation are priced as disjoint here, so an overlap would certify an
    # optimum the engine will not honour.
    assert not any(
        credit[t] > 0 and order_mw[t] > 0 for t in range(n)
    ), "appeal and order windows overlap; supersession is not encoded here (#183)"

    candidates = [t for t in range(n) if price[t] + credit[t] > fuel[t] and G > 0]
    credited = [t for t in range(n) if credit[t] > 0]
    ridx = {t: i for i, t in enumerate(credited)}
    m = len(credited)
    # Absorption (#369) is the exact mirror of relief: relief is
    # max(0, d+g-c) and absorption is max(0, c-d-g), so it gets a mirrored
    # variable and a mirrored disjunction rather than a special case.
    absorbing_hours = [t for t in range(n) if absorb_credit[t] > 0]
    aidx = {t: i for i, t in enumerate(absorbing_hours)}
    ma = len(absorbing_hours)

    def solve(
        gas_hours: frozenset[int],
        reducing: frozenset[int],
        absorbing: frozenset[int] = frozenset(),
    ) -> float | None:
        # `reducing`: credited hours branched as net-reducing (credit flows,
        # d+g-c >= 0 enforced); other credited hours branch as net-charging
        # (r pinned to 0, charging free). The engine's relief floor
        # max(0, d+g-c) is a per-hour disjunction — this enumeration makes
        # the LP exact instead of outlawing charge during credited hours.
        #
        # `absorbing`: the same branching for absorption hours. An hour
        # branched as net-absorbing earns credit on c-d-g and is constrained
        # non-negative there; one branched the other way pins a_t to 0, which
        # is what lets the solver decline an offer it cannot profit from.
        g = [G if t in gas_hours else 0.0 for t in range(n)]
        # vars: c_0..c_{n-1}, d_0..d_{n-1}, r_0..r_{m-1}, a_0..a_{ma-1}
        nv = 2 * n + m + ma
        obj = [0.0] * nv
        for t in range(n):
            obj[t] = price[t]          # charging buys extra
            obj[n + t] = -price[t]     # discharging avoids buying
        for t in credited:
            obj[2 * n + ridx[t]] = -credit[t]
        for t in absorbing_hours:
            obj[2 * n + m + aidx[t]] = -absorb_credit[t]
        const = sum(price[t] * it[t] for t in range(n)) + sum((fuel[t] - price[t]) * g[t] for t in gas_hours)

        rows, rhs = [], []
        for t in range(n):  # SOC prefix bounds
            hi = [0.0] * nv
            for tau in range(t + 1):
                hi[tau] = eta
                hi[n + tau] = -1.0
            rows.append(hi)
            rhs.append(E - s0)
            rows.append([-x for x in hi])
            rhs.append(s0)
        for t in credited:
            if t in reducing:  # r_t <= d_t + g_t - c_t, and d_t + g_t - c_t >= 0
                row = [0.0] * nv
                row[2 * n + ridx[t]] = 1.0
                row[n + t] = -1.0
                row[t] = 1.0
                rows.append(row)
                rhs.append(g[t])
                row2 = [0.0] * nv
                row2[t] = 1.0
                row2[n + t] = -1.0
                rows.append(row2)
                rhs.append(g[t])
        for t in absorbing_hours:
            if t in absorbing:  # a_t <= c_t - d_t - g_t, and c_t - d_t - g_t >= 0
                row = [0.0] * nv
                row[2 * n + m + aidx[t]] = 1.0
                row[t] = -1.0
                row[n + t] = 1.0
                rows.append(row)
                rhs.append(-g[t])
                row2 = [0.0] * nv
                row2[n + t] = 1.0
                row2[t] = -1.0
                rows.append(row2)
                rhs.append(-g[t])
        for t in range(n):  # full delivery: d_t + g_t - c_t >= order_mw[t]
            if order_mw[t] > 0:
                row = [0.0] * nv
                row[t] = 1.0
                row[n + t] = -1.0
                rows.append(row)
                rhs.append(g[t] - order_mw[t])

        bounds = (
            [(0.0, P) for _ in range(n)]
            + [(0.0, min(P, max(0.0, it[t] - g[t]))) for t in range(n)]
            + [(0.0, it[credited[i]] if credited[i] in reducing else 0.0) for i in range(m)]
            # Absorption is bounded by battery power: c - d - g <= P.
            + [(0.0, P if absorbing_hours[i] in absorbing else 0.0) for i in range(ma)]
        )
        res = linprog(obj, A_ub=rows, b_ub=rhs, bounds=bounds, method="highs")
        if not res.success:
            return None
        return const + res.fun, res.x

    best: float | None = None
    best_plan: dict | None = None
    branchings = [
        frozenset(sub)
        for k2 in range(0, m + 1)
        for sub in combinations(credited, k2)
    ]
    # The absorption branching is the mirror of the relief one. With no
    # absorption hours this is exactly [frozenset()], so the loop below runs
    # the identical number of solves as before and every existing pack is
    # untouched (#369).
    absorb_branchings = [
        frozenset(sub)
        for k2 in range(0, ma + 1)
        for sub in combinations(absorbing_hours, k2)
    ]
    for k in range(0, min(permits, len(candidates)) + 1):
        for combo in combinations(candidates, k):
            for reducing in branchings:
                for absorbing in absorb_branchings:
                    out = solve(frozenset(combo), reducing, absorbing)
                    if out is None:
                        continue
                    v, x = out
                    if best is None or v < best:
                        best = v
                        # The argmin, translated to engine actions: the parity
                        # test (web/tests/optimal.test.ts) needs the LINE, not
                        # just the number — gold must be reproducible in the
                        # real engine.
                        best_plan = {
                            "gas_hours": sorted(combo),
                            "reducing": sorted(reducing),
                            "absorbing": sorted(absorbing),
                            "battery_mw": [round(x[n + t] - x[t], 4) for t in range(n)],
                        }
    assert best is not None, "no feasible fully-delivering play"
    if return_plan:
        assert best_plan is not None
        best_plan["cost"] = round(best, 2)
        return best_plan
    return round(best, 2)


def optimal_line(pack: dict, plan: dict) -> list[dict]:
    """The solver's argmin as engine actions (the Action shape in
    web/shared/engine.ts), so the parity test replays it without translating.

    Both optimizers return the same plan shape: the permit hours they bought,
    the credited hours they chose to reduce in, and per-turn battery power
    signed the way the engine reads it (+ discharge, - charge). The MILP also
    returns each turn's gas output, which a stock can hold below full (#582),
    and, under an import limit, each turn's curtailment (#583). Turning that
    into a line is four lines of arithmetic, and doing it HERE rather than by
    hand in TypeScript is the whole point of #212 — one translation, in one
    place, instead of one per pack maintained by eye.
    """
    gas_mw = pack["site"]["diesel"]["power_mw"]
    gas_hours = set(plan["gas_hours"])
    reducing = set(plan["reducing"])
    # Absent on plans from the MILP, which does not price absorption (#369).
    absorbing = set(plan.get("absorbing", []))
    line = []
    for t in range(pack["turns"]):
        action = {
            "curtail_mw": plan["curtail_mw"][t] if "curtail_mw" in plan else 0,
            "battery_mw": plan["battery_mw"][t],
            "diesel_mw": plan["gas_mw"][t] if "gas_mw" in plan else (gas_mw if t in gas_hours else 0),
        }
        # Only credited hours the solver chose to reduce in accept the offer;
        # the engine pays no credit on an ordered turn anyway (#183). An
        # absorption hour the solver chose to draw in accepts for the same
        # reason, and the two sets cannot overlap.
        if t in reducing or t in absorbing:
            action["accept_offer"] = True
        line.append(action)
    # Each commitment's chosen quantity goes on its decision turn (#464).
    for cmt in pack.get("commitments", []):
        turn = line[cmt["decision_turn"]]
        turn["commit"] = {**turn.get("commit", {}), cmt["id"]: plan["commit"][cmt["id"]]}
    # The chosen fuel supply goes on turn 0, the only turn it is read (#469).
    if "supply_options" in pack["site"]["diesel"]:
        line[0]["supply"] = plan["supply"]
    # On a dual-fuel plant every turn names its fuel (#707), as the engine's
    # applied action does, so the line does not lean on what a turn inherits.
    if "alternate_fuel" in pack["site"]["diesel"]:
        for t, action in enumerate(line):
            action["fuel"] = plan["fuel"][t]
    return line


def write_plan(pack: dict, plan: dict, solver: str, out: Path) -> None:
    """Write the certified plan beside the catalogue as durable evidence.

    Deliberately NOT under data-g/packs/: the worker lists the R2 `packs/`
    prefix and parses every object it finds as a scenario pack, so a plan
    sitting in that namespace would become a garbage catalogue entry the
    first time anything bulk-seeds the bucket.
    """
    doc = {
        "scenario_id": pack["scenario_id"],
        "pack_version": pack["pack_version"],
        "score_version": pack["scoring"]["score_version"],
        "solver": solver,
        "optimal_cost_usd": pack["scoring"]["optimal_cost_usd"],
        "line": optimal_line(pack, plan),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def fetch_csv(dest: Path, url: str = RTS_GMLC_LOAD_URL) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    with urllib.request.urlopen(url) as resp:  # noqa: S310 — pinned https URL
        tmp.write_bytes(resp.read())
    tmp.replace(dest)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compile the S-03 scenario pack from RTS-GMLC load data.")
    ap.add_argument("--csv", type=Path, default=REPO_ROOT / "data" / "rts-gmlc" / "DAY_AHEAD_regional_Load.csv")
    ap.add_argument(
        "--wind-csv", type=Path, default=REPO_ROOT / "data" / "rts-gmlc" / "DAY_AHEAD_wind.csv"
    )
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data-g" / "packs" / "s-03.pack.json")
    ap.add_argument("--tutorial-out", type=Path, default=REPO_ROOT / "data-g" / "packs" / "s-00.pack.json")
    ap.add_argument("--plans-out", type=Path, default=REPO_ROOT / "data-g" / "plans")
    ap.add_argument("--fetch", action="store_true", help="download the source CSVs if missing")
    args = ap.parse_args(argv)

    if args.fetch and not args.csv.exists():
        print(f"fetching {RTS_GMLC_LOAD_URL}")
        fetch_csv(args.csv)
    if args.fetch and not args.wind_csv.exists():
        print(f"fetching {RTS_GMLC_WIND_URL}")
        fetch_csv(args.wind_csv, RTS_GMLC_WIND_URL)

    rows = read_load_csv(args.csv)
    # The wind file has the load file's layout, one column per plant, so the
    # same reader sums the four plants into the hour's total output.
    wind_rows = read_load_csv(args.wind_csv)
    # S-09 Price-Maker (#159): grid response ACTIVATED as its own scenario,
    # per the 0004 road. Same compiled day as S-03; the difference is that
    # the grid answers back — slope (#69), responsive status (#133), honest
    # fog (#134) — and the settlement prices what you did to the neighbors
    # (#147). S-03's live era is untouched: a new id disturbs nobody.
    responsive = compile_s03(rows, responsive=True)
    responsive["scenario_id"] = "S-09"
    responsive["title"] = "Price-Maker"
    responsive["pack_version"] = "0.1.0"  # new scenario, its own version line
    responsive["brief_md"] = S09_BRIEF_MD
    responsive["provenance"]["notes"] += (
        " S-09 PRICE-MAKER (#159): the S-03 day with grid response ACTIVE. Carries "
        "price_slope_usd_per_mwh_per_mw (#69, the analytic derivative of the documented "
        "curve); status_response (0004 v1, the hourly system loads plus the percentile "
        "thresholds that derived the static strip, so realized status includes the "
        "campus's deviation); and forecast (0004 v2): PURE PERSISTENCE, every future "
        "hour forecast at the current hour's value, deterministic and deliberately blind "
        "to the cliff. No optimal_cost_usd: the exact optimizer is slope-free by "
        "assertion, so this pack awards no stars rather than unverified ones (#152)."
    )
    s10 = compile_s10(rows)
    # S-07 Heat Dome (#163): 72 turns is past the enumerator's reach, so its
    # optimum comes from the exact MILP and is stamped here before validation.
    s07 = compile_s07(rows)
    s07_plan = compute_optimal_milp(s07)
    s07["scoring"]["optimal_cost_usd"] = s07_plan["cost"]
    print(
        f"  S-07 MILP optimum ${s07_plan['cost']:,.2f} | gas {s07_plan['gas_hours']} "
        f"| reducing {s07_plan['reducing']}"
    )
    # S-11 The Consumables Cliff (#440): the first catalogue pack with a stock,
    # which only the MILP models (#582).
    s11 = compile_s11(rows)
    s11_plan = compute_optimal_milp(s11)
    s11["scoring"]["optimal_cost_usd"] = s11_plan["cost"]
    print(
        f"  S-11 MILP optimum ${s11_plan['cost']:,.2f} | gas {s11_plan['gas_hours']} "
        f"| reducing {s11_plan['reducing']}"
    )
    # S-12 Amplified (#443) is slope-free with no stock or limit, so the
    # enumerator below certifies it. S-13 The Ice Storm (#478) carries an
    # import limit, which only the MILP models (#583).
    s12 = compile_s12(rows)
    s13 = compile_s13(rows)
    s13_plan = compute_optimal_milp(s13)
    s13["scoring"]["optimal_cost_usd"] = s13_plan["cost"]
    print(
        f"  S-13 MILP optimum ${s13_plan['cost']:,.2f} | gas {s13_plan['gas_hours']} "
        f"| reducing {s13_plan['reducing']}"
    )
    # The commitment scenarios (#442, #476, #481) carry commitments, S-18
    # (#480) carries supply options, S-19 (#475) a capped nomination and a
    # flow order, and S-20 (#441) an emergency order, which only the MILP
    # models (#464, #469, #635, #465); it chooses each quantity and the supply.
    s15, s16, s17 = compile_s15(rows), compile_s16(rows), compile_s17(rows)
    s18, s19, s20 = compile_s18(rows), compile_s19(rows), compile_s20(rows)
    # S-23 The Barge (#473): S-11's days on a dual-fuel plant (#707) with a
    # weekend nomination, which only the MILP models.
    s23 = compile_s23(rows)
    commitment_plans = {}
    for p in (s15, s16, s17, s18, s19, s20, s23):
        cplan = compute_optimal_milp(p)
        p["scoring"]["optimal_cost_usd"] = cplan["cost"]
        commitment_plans[p["scenario_id"]] = cplan
        print(
            f"  {p['scenario_id']} MILP optimum ${cplan['cost']:,.2f} | commit {cplan.get('commit')} "
            f"| supply {cplan.get('supply')} | gas {cplan['gas_hours']} | reducing {cplan['reducing']}"
            + (f" | fuel {cplan['fuel']}" if "fuel" in cplan else "")
        )
    # S-14 The Wind Came Through (#482) prices net load, so it may not play a
    # day the load-priced packs play. Its absorption appeal needs the
    # enumerator, which certifies it below.
    # S-21 Twelve Hours Dark (#477) is S-03's day with the price frozen; its
    # outage is inert to the optimizers, so the enumerator certifies it below.
    s21 = compile_s21(rows)
    # S-22 The Same Afternoon (#697) is S-21 with the outage silent; inert too.
    s22 = compile_s22(rows)
    taken: set[tuple[int, int, int]] = set()
    for other in (s10, s07, s11, s12, s13, s15, s16, s17, s18, s19, s20, s21, s22, s23):
        taken |= played_days(other)
    s14 = compile_s14(rows, wind_rows, frozenset(taken))
    # S-08 The Peninsula (#137): the first pack built on OBSERVED data rather
    # than a derived price model. `_system_mw` is a build-log aid, not part of
    # the contract, so it never reaches the schema or the bucket.
    s08 = compile_s08()
    s08_system = s08.pop("_system_mw")
    print(f"  S-08 window system load {min(s08_system):,.0f}-{max(s08_system):,.0f} MW"
          f" | price ${min(s08['grid']['price_usd_per_mwh']):.2f}"
          f" to ${max(s08['grid']['price_usd_per_mwh']):.2f}/MWh"
          f" | {sum(1 for s in s08['grid']['system_status'] if s == 'emergency')} emergency hours")
    packs = (
        (compile_s03(rows), args.out),
        (compile_s00(), args.tutorial_out),
        (responsive, args.out.parent / "s-09.pack.json"),
        (s10, args.out.parent / "s-10.pack.json"),
        (s07, args.out.parent / "s-07.pack.json"),
        (s08, args.out.parent / "s-08.pack.json"),
        (s11, args.out.parent / "s-11.pack.json"),
        (s12, args.out.parent / "s-12.pack.json"),
        (s13, args.out.parent / "s-13.pack.json"),
        (s14, args.out.parent / "s-14.pack.json"),
        (s15, args.out.parent / "s-15.pack.json"),
        (s16, args.out.parent / "s-16.pack.json"),
        (s17, args.out.parent / "s-17.pack.json"),
        (s18, args.out.parent / "s-18.pack.json"),
        (s19, args.out.parent / "s-19.pack.json"),
        (s20, args.out.parent / "s-20.pack.json"),
        (s21, args.out.parent / "s-21.pack.json"),
        (s22, args.out.parent / "s-22.pack.json"),
        (s23, args.out.parent / "s-23.pack.json"),
    )
    # The binding difficulty ordering (#126), stamped as data so the play
    # page can render the catalogue as the ladder it is.
    #
    # S-08 sits at 1, not at the top (#371). It first shipped at rank 5 for
    # being newest, which is exactly the reasoning the decree exists to stop.
    # By the decree's own axes it demands more than S-00 (10 turns vs 6, a
    # 300 MW site vs 100, no coach track) and less than S-03 (16 turns and
    # two events vs 10 and none). Novelty is not difficulty: observed data
    # and the inverted status mapping make it the most interesting entry,
    # and the ladder does not measure interesting. It earns a high rank when
    # it grows the collapse and restoration acts (#369), not by being new.
    #
    # S-11 sits above S-07 (#440): the same seventy-two-hour horizon and three
    # orders, plus a stock to ration whose refill the brief promises wrongly.
    #
    # The winter batch (#482, #443, #478) enters by demand, not by date:
    # S-14 sits above S-09 (a forecast that changes sign, and both appeal
    # types in one day, though no order); S-12 above S-14 (a mandatory order
    # under a forecast that is low every hour); S-13 above S-10 (a forced
    # island, obligations the site cannot fully serve, and a staged pickup)
    # and below S-07, whose seventy-two turns stay the longer horizon.
    #
    # The commitment batch (#442, #476, #481) each adds a decision at turn 0
    # that the rest of the episode settles against. S-15 sits above S-09 (S-03's
    # day, with the day's gas fixed at 06:00 against an honest outlook) and
    # below S-14, whose forecast changes sign. S-16 sits above S-12: the same
    # kind of fog with the opposite sign, and a commitment to be wrong against.
    # S-17 sits above S-07 (the same three days with a promise every order
    # settles against) and below S-11, whose refill is promised wrongly and
    # whose stock the screen cannot see coming.
    #
    # S-18 (#480) sits above S-07 and below S-17: the same three days with a
    # choice at turn 0 that decides which fuel exists on which day. It is one
    # choice between two options whose terms are all in the brief, where
    # S-17's is a quantity whose limit is the permits it has to count.
    #
    # S-19 (#475) sits above S-15 and S-10, the rungs #475 names, and below
    # S-13: The Nomination's decision on a winter day, with a band that a flow
    # order halves mid-day and an order that needs the nomination's gas, where
    # S-13 forces an island the site cannot fully serve.
    #
    # S-20 (#441) sits directly above S-03 and below S-09, the rungs #441
    # names: S-03's day with half the permit hours and one order whose
    # condition decides which hours it covers, where S-09's grid answers back.
    #
    # S-21 (#477) sits above S-03 and below S-09, the rungs #477 names, and
    # above S-20: S-03's assets and order with the price gone for twelve
    # hours, where S-20's terms are all on an honest screen. S-09's forecast
    # is blind to the cliff all day and its grid answers back.
    #
    # S-22 (#697) sits directly above S-21 and below S-09: S-21's day and
    # outage with nothing on the screen saying the price is old, where S-21
    # marks it. S-09's forecast is blind to the cliff on a screen that is live.
    #
    # S-23 (#473) is the Tier 2 version of S-11's situation and sits above it,
    # at the top: S-11's three days with two fuels, two stocks, a weekend
    # nomination to keep and a barge that slips.
    ranks = {
        "S-00": 0, "S-08": 1, "S-03": 2, "S-20": 3, "S-21": 4, "S-22": 5,
        "S-09": 6, "S-15": 7, "S-14": 8, "S-12": 9, "S-16": 10, "S-10": 11,
        "S-19": 12, "S-13": 13, "S-07": 14, "S-18": 15, "S-17": 16, "S-11": 17,
        "S-23": 18,
    }
    for pack, _ in packs:
        pack["difficulty_rank"] = ranks[pack["scenario_id"]]
    # Certified plans, keyed by scenario. S-07's, S-11's, S-13's and the
    # commitment batch's came from the MILP above; the rest are enumerated
    # below. Packs with no optimum (S-09 carries a price slope, which both
    # optimizers refuse) get no plan and no stars.
    plans: dict[str, tuple[dict, str]] = {
        "S-07": (s07_plan, "milp"), "S-11": (s11_plan, "milp"), "S-13": (s13_plan, "milp"),
        **{sid: (cplan, "milp") for sid, cplan in commitment_plans.items()},
    }
    for pack, out in packs:
        # Slope-free packs get the enumerated exact optimum — unless one was
        # already stamped (S-07's comes from the MILP; re-enumerating a
        # 72-turn day would run for hours).
        if (
            "price_slope_usd_per_mwh_per_mw" not in pack["grid"]
            and "optimal_cost_usd" not in pack["scoring"]
        ):
            plan = compute_optimal_cost(pack, return_plan=True)
            pack["scoring"]["optimal_cost_usd"] = plan["cost"]
            plans[pack["scenario_id"]] = (plan, "enumerator")
        validate_pack(pack)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n")
        print(f"wrote {out}")
        print(f"  {pack['scenario_id']} · {pack['title']} · baseline ${pack['scoring']['baseline_cost_usd']:,.2f}")
    for pack, _ in packs:
        entry = plans.get(pack["scenario_id"])
        if entry is None:
            continue
        plan, solver = entry
        plan_out = args.plans_out / f"{pack['scenario_id'].lower()}.plan.json"
        write_plan(pack, plan, solver, plan_out)
        print(f"wrote {plan_out}  ({solver}, ${pack['scoring']['optimal_cost_usd']:,.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
