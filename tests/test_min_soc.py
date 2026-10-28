"""SoC-ondergrens: ontladen komt nooit onder de ondergrens, ondergrens 0 = ongewijzigd."""
from datetime import datetime, timedelta, timezone

from custom_components.virtual_battery.logic.simulation import SimBlock, SimInputs, simulate
from custom_components.virtual_battery.logic.planner import AMS


def _blocks(now):
    out = []
    for i in range(48):
        t = now + timedelta(minutes=15 * i)
        ms = int(t.timestamp() * 1000)
        out.append(SimBlock(ms, ms + 900000, 0.30 + 0.2 * (i % 8 > 3), 0.25))
    return out


def _run(floor, strategy="discharge_now"):
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    inp = SimInputs(now_ms=now_ms, strategy=strategy, feed_in_discount=0.0, max_margin=0.1,
                    soc_kwh=8.0, realised_today=0.0, cap_kwh=10.0, max_power_w=2500, wear_per_kwh=0.0,
                    profile=None, base_load_fallback_w=400, solar_map={}, solar_factor=0.0,
                    blocks=_blocks(now), min_soc_pct=floor)
    return simulate(inp)


def test_floor_respected():
    for strat in ("discharge_now", "zero_meter", "hybrid", "price_optimization"):
        res = _run(30.0, strat)
        assert min(v for _, v in res["soc_reeks"]) >= 3.0 - 0.002, strat


def test_floor_zero_discharges_to_empty():
    res = _run(0.0)
    assert min(v for _, v in res["soc_reeks"]) < 0.5
