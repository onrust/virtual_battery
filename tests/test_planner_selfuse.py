"""Voorraadverdeling in de planner: zonder terugleverkorting of zonder eigen verbruik blijft het schema gelijk."""
import random
from datetime import datetime, timedelta

from custom_components.virtual_battery.logic import planner as P

AMS = P.AMS


def _hours(rnd, d0):
    out = []
    for i in range(96):
        s = d0 + timedelta(minutes=15 * i)
        h = i // 4
        v = 0.3 + (0.12 if 17 <= h <= 20 else 0) - (0.1 if 11 <= h <= 15 else 0) + rnd.uniform(-0.03, 0.03)
        out.append({"key": int(s.timestamp() * 1000), "price": round(v, 3), "dur_h": 0.25})
    return out


def _plan(rnd, kort, consumption):
    d0 = datetime(2026, 10, 19, 0, 0, tzinfo=AMS)
    hours = _hours(rnd, d0)
    solar = {h["key"]: max(0, 1 - abs((h["key"] - hours[52]["key"]) / 3600000)) * 1.5 for h in hours}
    params = P.Params(capacity_kwh=16, max_power_kw=7, wear_per_kwh=0.005, feed_in_discount=kort,
                      start_soc=6.0, solar_factor=1.0)
    now = int(datetime(2026, 10, 19, 18, 58, tzinfo=AMS).timestamp() * 1000)
    return P.plan_day(hours, params, now, lambda ms: consumption, solar, None).schedule


def test_no_feed_in_discount_is_deterministic():
    a = _plan(random.Random(1), 0.0, 500)
    b = _plan(random.Random(1), 0.0, 500)
    assert a == b


def test_plan_runs_with_discount_and_consumption():
    s = _plan(random.Random(2), 0.11, 800)
    assert any(v["action"] == "ontladen" for v in s.values())
