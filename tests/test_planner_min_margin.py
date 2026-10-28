"""Minimale winst per geladen kWh: kleine cycli vallen weg, 0 = ongewijzigd."""
from datetime import datetime, timedelta

from custom_components.virtual_battery.logic.planner import AMS, Params, make_consumption_fn, plan_day


def _hours(prices):
    start = datetime(2026, 10, 26, 0, 0, tzinfo=AMS)
    return [{"key": int((start + timedelta(minutes=15 * i)).timestamp() * 1000), "price": p, "dur_h": 0.25}
            for i, p in enumerate(prices)]


def _plan(min_margin):
    # goedkoop kwartier (0,34) gevolgd door duur kwartier (0,445): marge ~0,033/kWh na rendement en slijtage
    prices = [0.40] * 96
    prices[4] = 0.34
    for i in range(32, 36):
        prices[i] = 0.445
    hours = _hours(prices)
    params = Params(capacity_kwh=16, max_power_kw=7, wear_per_kwh=0.005, feed_in_discount=0.11,
                    start_soc=0.0, min_soc_pct=0.0, solar_factor=0.0, min_margin=min_margin)
    return plan_day(hours, params, hours[0]["key"], make_consumption_fn(None, 600), {})


def _acties(res):
    return {v["action"] for v in res.schedule.values()}


def test_zonder_marge_wordt_gecycled():
    assert "laden" in _acties(_plan(0.0))


def test_marge_boven_voordeel_geeft_geen_cyclus():
    assert "laden" not in _acties(_plan(0.05))


def test_marge_onder_voordeel_blijft_gecycled():
    assert "laden" in _acties(_plan(0.01))
