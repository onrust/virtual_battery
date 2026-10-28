"""Zonvoorspelling verwerken + bijsturen (nowcast). Port van Node-RED 'Zonvoorspelling verwerken' (eb1a0000z4).

raw/corr: {epoch_ms van kwartier: kWh}.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from .planner import AMS


def jsround(x):
    return math.floor(x + 0.5)


def day_of(ms):
    return datetime.fromtimestamp(ms / 1000, AMS).strftime("%Y-%m-%d")


def parse_forecast(*entities_attrs_wh_period_15m) -> dict:
    """Elk argument is het attribuut `wh_period_15m` ({iso-tijd: Wh}) van een Open-Meteo-sensor."""
    raw = {}
    for p in entities_attrs_wh_period_15m:
        for t, wh in (p or {}).items():
            try:
                key = int(round(datetime.fromisoformat(str(t)).timestamp() * 1000))
                v = float(wh)
            except (TypeError, ValueError):
                continue
            if math.isnan(v):
                continue
            raw[key] = v / 1000
    return raw


def solar_factor(percent) -> float:
    try:
        f = float(percent)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(f):
        return 0.0
    return min(1.0, max(0.0, f / 100))


def nowcast(raw: dict, actual_change_kwh: dict, now_ms: int) -> dict:
    """actual_change_kwh: {uurstart_ms: gemeten PV-opbrengst kWh} (statistiek 'change')."""
    now_hour = (now_ms // 3600000) * 3600000
    today = day_of(now_ms)
    f_hour = {}
    for k, v in raw.items():
        h = (k // 3600000) * 3600000
        f_hour[h] = f_hour.get(h, 0) + v
    sa = sf = 0.0
    n = 0
    h = now_hour - 3 * 3600000
    while h < now_hour:
        if day_of(h) == today and h in actual_change_kwh:
            fh = f_hour.get(h, 0)
            if fh >= 0.15:
                sa += actual_change_kwh[h]
                sf += fh
                n += 1
        h += 3600000
    ratio = 1.0
    if n >= 1 and sf >= 0.4:
        ratio = min(2.5, max(0.5, sa / sf))
    corr = {}
    for k, v in raw.items():
        dh = (k - now_ms) / 3600000
        corr[k] = v if dh < -0.25 else v * (1 + (ratio - 1) * math.exp(-max(0, dh) / 3))
    return {"corr": corr, "ratio": ratio, "hours_used": n, "measured": sa, "forecast": sf}


def hourly_sensor(raw: dict, corr: dict, ratio: float, n_hours: int, now_ms: int) -> dict:
    """Uurlijkse bijgestuurde prognose als sensor-payload (state + attributen)."""
    today = day_of(now_ms)
    uur_c, uur_r = {}, {}
    tot_c = 0.0
    for k, v in raw.items():
        h = (k // 3600000) * 3600000
        uur_c[h] = uur_c.get(h, 0) + corr[k] * 1000
        uur_r[h] = uur_r.get(h, 0) + v * 1000
        if day_of(k) == today:
            tot_c += corr[k]
    wh_c, wh_r = {}, {}
    for h in sorted(uur_c):
        label = datetime.fromtimestamp(h / 1000, AMS).isoformat()
        wh_c[label] = jsround(uur_c[h])
        wh_r[label] = jsround(uur_r[h])
    return {"state": jsround(tot_c * 100) / 100,
            "attributes": {"wh_period": wh_c, "wh_period_raw": wh_r,
                           "nowcast_ratio": jsround(ratio * 100) / 100, "nowcast_uren": n_hours}}
