"""Verbruiksprofiel (7 x 24 W, maandag = 0). Port van Node-RED 'Verbruiksprofiel berekenen' (eb1a0000v3).

stats: {statistic_id: [{"start": ms, "change": kWh}, ...]} (uurlijkse meterverschillen).
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from .planner import AMS

PV = "pv"
IMPORT = "import"
EXPORT = "export"
CAR = "car"


def jsround(x):
    return math.floor(x + 0.5)


def _f(v, default=0.0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(f) or f == 0 else f


def weeks_param(w) -> int:
    return min(6, max(2, jsround(_f(w, 4))))


def window(now_ms: int, weeks) -> tuple:
    """(eind_uur_ms, begin_ms) van het opgevraagde venster."""
    n = weeks_param(weeks)
    end = (now_ms // 3600000) * 3600000
    return end, end - n * 7 * 24 * 3600000


def compute_profile(series: dict, end_hour_ms: int, weeks, weight_last_pct, mix_pct, fallback_w, now_ms: int):
    """series: {PV|IMPORT|EXPORT|CAR: {uurstart_ms: kWh}}. Retourneert (profiel, details)."""
    N = weeks_param(weeks)
    begin = end_hour_ms - N * 7 * 24 * 3600000
    fb = _f(fallback_w, 400)
    g = min(1.0, max(0.0, _f(weight_last_pct, 0) / 100))
    m = min(1.0, max(0.0, _f(mix_pct, 0) / 100))
    w_week = [g if k == 0 else (1 - g) / (N - 1) for k in range(N)]

    pv, imp, exp, car = (series.get(x, {}) for x in (PV, IMPORT, EXPORT, CAR))
    cel = [[[[] for _ in range(N)] for _ in range(24)] for _ in range(7)]
    used = 0
    s = begin
    while s < end_hour_ms:
        if s in pv and s in imp and s in exp:
            kwh = pv[s] + imp[s] - exp[s] - car.get(s, 0)
            if math.isfinite(kwh) and kwh <= 25:
                w = max(0, kwh) * 1000
                dt = datetime.fromtimestamp(s / 1000, AMS)
                k = min(N - 1, (end_hour_ms - s - 1) // (7 * 86400000))
                cel[dt.weekday()][dt.hour][k].append(w)
                used += 1
        s += 3600000

    def gem(a):
        return sum(a) / len(a)

    raw = []
    for d in range(7):
        row = []
        for h in range(24):
            som = wsom = 0.0
            for k in range(N):
                a = cel[d][h][k]
                if not a:
                    continue
                som += w_week[k] * gem(a)
                wsom += w_week[k]
            if wsom > 0:
                row.append(som / wsom)
            else:
                alle = [x for k in range(N) for x in cel[d][h][k]]
                row.append(gem(alle) if alle else None)
        raw.append(row)

    groep = [[], []]
    uur_gem = []
    for h in range(24):
        for t in range(2):
            dagen = [0, 1, 2, 3, 4] if t == 0 else [5, 6]
            vals = [raw[d][h] for d in dagen if raw[d][h] is not None]
            groep[t].append(gem(vals) if vals else None)
        alle = [r[h] for r in raw if r[h] is not None]
        uur_gem.append(gem(alle) if alle else None)

    profiel = []
    for d in range(7):
        row = []
        for h in range(24):
            t = 0 if d < 5 else 1
            gv = groep[t][h]
            if raw[d][h] is not None:
                v = (1 - m) * raw[d][h] + m * gv if gv is not None else raw[d][h]
            else:
                v = gv if gv is not None else (uur_gem[h] if uur_gem[h] is not None else fb)
            row.append(jsround(v))
        profiel.append(row)

    komende = []
    for k in range(48):
        t = end_hour_ms + k * 3600000
        dt = datetime.fromtimestamp(t / 1000, AMS)
        komende.append([t, profiel[dt.weekday()][dt.hour]])
    return profiel, {"hours_used": used, "weeks": N, "upcoming": komende,
                     "weight_last": g, "weight_older": (1 - g) / (N - 1) if N > 1 else 0, "mix": m}
