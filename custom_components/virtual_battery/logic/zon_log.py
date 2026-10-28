"""Dagelijkse zonlog (port van Node-RED lg2/lg7) en dagwissel (dw1). Pure Python."""
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Optional

from .planner import AMS


def _jsround3(x):
    return math.floor(x * 1000 + 0.5) / 1000


def _day(ms):
    return datetime.fromtimestamp(ms / 1000, AMS).strftime("%Y-%m-%d")


def _hh(ms):
    return "%02d" % datetime.fromtimestamp(ms / 1000, AMS).hour


def forecast_record(raw: dict, factor, now_ms: int) -> Optional[str]:
    """JSONL-regel met de ruwe uurprognose van vandaag (kWh), of None als er geen prognose is."""
    if not raw:
        return None
    dag = _day(now_ms)
    uur, tot = {}, 0.0
    for k, v in raw.items():
        if _day(k) != dag:
            continue
        u = _hh(k)
        uur[u] = _jsround3(uur.get(u, 0) + v)
        tot += v
    rec = {"t": "prognose", "datum": dag, "zekerheid": factor, "uur": uur,
           "dag_totaal": math.floor(tot * 100 + 0.5) / 100}
    return json.dumps(rec, separators=(",", ":"))


def actual_record(pv: dict, imp: dict, exp: dict, car: dict, now_ms: int) -> str:
    """JSONL-regel met gemeten PV en huisverbruik (excl. auto) per uur van de dag die 30 min geleden liep."""
    dag = _day(now_ms - 30 * 60000)
    sel = lambda m: {s: v for s, v in m.items() if v is not None and math.isfinite(v) and _day(s) == dag}
    pv, imp, exp, car = sel(pv), sel(imp), sel(exp), sel(car)
    pv_u, huis_u = {}, {}
    pv_t = huis_t = 0.0
    for s in pv:
        if s not in imp or s not in exp:
            continue
        h = max(0, pv[s] + imp[s] - exp[s] - car.get(s, 0))
        pv_u[_hh(s)] = _jsround3(pv[s])
        huis_u[_hh(s)] = _jsround3(h)
        pv_t += pv[s]
        huis_t += h
    n = len(pv_u)
    rec = {"t": "actueel", "datum": dag, "partieel": n < 23, "uren": n, "pv": pv_u, "huis": huis_u,
           "pv_dag": math.floor(pv_t * 100 + 0.5) / 100, "huis_dag": math.floor(huis_t * 100 + 0.5) / 100}
    return json.dumps(rec, separators=(",", ":"))


def day_rollover(state: dict, now_ms: int) -> dict:
    """Dagwissel vóór de engine. state: {'datum', 'reset_tot_ms', 'opbrengst_vandaag'}.
    Geeft (eventueel aangepaste) state terug plus 'override_vandaag' (waarde die de engine 15 s lang krijgt) of None."""
    vandaag = _day(now_ms)
    vorige = state.get("datum")
    if vorige and vorige != vandaag:
        state["opbrengst_vandaag"] = 0
        state["reset_tot_ms"] = now_ms + 15000
    state["datum"] = vandaag
    override = None
    if now_ms < (state.get("reset_tot_ms") or 0):
        override = state.get("opbrengst_vandaag") or 0
    return {"state": state, "override_vandaag": override}
