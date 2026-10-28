"""Eigen verbruik nu uit de batterij en later goedkoop bijladen (ontladen vóór laden)."""
import math
from datetime import datetime, timedelta

from custom_components.virtual_battery.logic.planner import AMS, ONEWAY, Params, make_consumption_fn, plan_day

CAP = 10.0


def _hours(prices):
    start = datetime(2026, 11, 3, 16, 0, tzinfo=AMS)
    return [{"key": int((start + timedelta(minutes=15 * i)).timestamp() * 1000), "price": p, "dur_h": 0.25}
            for i, p in enumerate(prices)]


def _prices(avond):
    # 16:00-22:00 avond (24 kwartieren), nacht 22:00-06:00 dal 0,15, 06:00-08:00 ochtendpiek 06:00-12:00 0,50
    return [avond] * 24 + [0.15] * 32 + [0.50] * 24


def _plan(avond, shift, min_margin=0.03):
    hours = _hours(_prices(avond))
    params = Params(capacity_kwh=CAP, max_power_kw=3.5, wear_per_kwh=0.005, feed_in_discount=0.11,
                    start_soc=CAP, min_soc_pct=0.0, solar_factor=0.0, min_margin=min_margin, shift_own_use=shift)
    return hours, plan_day(hours, params, hours[0]["key"], make_consumption_fn(None, 1000), {})


def _soc(res):
    soc, lo, hi = CAP, CAP, CAP
    for c, d in zip(res.charge, res.discharge):
        soc += c * ONEWAY - d / ONEWAY
        lo, hi = min(lo, soc), max(hi, soc)
    return lo, hi


def test_avondpiek_uit_batterij_en_nacht_bijladen():
    hours, res = _plan(0.35, True)
    avond = [res.schedule[h["key"]]["action"] for h in hours[:24]]
    nacht = [res.schedule[h["key"]]["action"] for h in hours[24:56]]
    assert "ontladen" in avond
    assert "laden" in nacht
    lo, hi = _soc(res)
    assert lo > -1e-6 and hi < CAP + 1e-6


def test_lage_avondprijs_geen_cyclus():
    # 0,17 * 0,85 - 0,15 = -0,005: niet rendabel
    hours, res = _plan(0.17, True)
    assert all(res.schedule[h["key"]]["action"] != "ontladen" for h in hours[:24])


def test_minimale_winst_blokkeert_verschuiving():
    # 0,24 * 0,85 - 0,15 - 0,005 = 0,049: onder 0,10 minimale winst verandert de stap niets
    _, met = _plan(0.24, True, min_margin=0.10)
    _, zonder = _plan(0.24, False, min_margin=0.10)
    assert met.schedule == zonder.schedule


def test_verschuiving_wijzigt_schema_boven_minimale_winst():
    # eigen verbruik 1 kW dekt maar een deel van het kwartier; de stap mag SoC-grenzen nooit schenden
    _, res = _plan(0.35, True)
    lo, hi = _soc(res)
    assert lo > -1e-6 and hi < CAP + 1e-6
    assert sum(res.charge) > 0
