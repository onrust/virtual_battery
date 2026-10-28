"""Dagschema-planner (port van Node-RED functie 'Dagschema optimaliseren', eb1a0000b1).

Pure Python, geen Home Assistant-afhankelijkheden. Tijden zijn epoch-milliseconden
(zoals in de Node-RED flow), energie in kWh, vermogen in W, prijzen in EUR/kWh.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

RTE = 0.85
ONEWAY = math.sqrt(RTE)
MIN_WINST_ZON_PLAN = 0.10
BLOCK_MS = 15 * 60000
AMS = ZoneInfo("Europe/Amsterdam")


def _num(v, default):
    """Zoals JS `parseFloat(x) || default`."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or f == 0:
        return default
    return f


@dataclass
class Params:
    capacity_kwh: float = 15.0
    max_power_kw: float = 9.0
    wear_per_kwh: float = 0.0          # EUR per geladen kWh
    feed_in_discount: float = 0.0      # terugleverkorting (EUR/kWh)
    start_soc: float = 0.0             # kWh
    min_soc_pct: float = 0.0           # SoC-ondergrens (% van capaciteit)
    solar_factor: float = 0.0          # zon-zekerheid (0..1)
    base_load_w: float = 400.0         # fallback als er geen profiel is
    min_margin: float = 0.0            # minimale winst per geladen kWh (EUR); 0 = uit
    shift_own_use: bool = True         # eigen verbruik nu uit de batterij, later goedkoop bijladen


@dataclass
class PlanResult:
    schedule: dict                     # {ms: {"action": ..., "power_w": ...}}
    plan: str
    solar_surplus_kwh: float
    running_series: Optional[str]
    n_blocks: int
    safety: int
    charge: list = field(default_factory=list)
    discharge: list = field(default_factory=list)


def make_consumption_fn(profile, base_load_w: float) -> Callable[[int], float]:
    """profile: 7 x 24 (maandag = 0) in W, of None."""
    cache: dict = {}

    def verbruik_w(ms: int) -> float:
        if not profile:
            return base_load_w
        k = ms // 3600000
        if k in cache:
            return cache[k]
        dt = datetime.fromtimestamp(ms / 1000, AMS)
        try:
            v = profile[dt.weekday()][dt.hour]
        except (IndexError, KeyError, TypeError):
            v = None
        r = base_load_w if v is None or (isinstance(v, float) and math.isnan(v)) else v
        cache[k] = r
        return r

    return verbruik_w


def parse_prices(raw_today, raw_tomorrow, tomorrow_valid):
    """Nordpool raw_today/raw_tomorrow -> lijst blokken {key, price, dur_h}."""
    out = []
    for h in list(raw_today or []) + (list(raw_tomorrow or []) if tomorrow_valid else []):
        start = datetime.fromisoformat(str(h["start"]))
        end = datetime.fromisoformat(str(h["end"]))
        dur = (end - start).total_seconds() / 3600
        price = h.get("value")
        if price is None:
            continue
        out.append({"key": int(round(start.timestamp() * 1000)),
                    "price": float(price), "dur_h": dur if dur > 0 else 0.25})
    return out


def plan_day(hours, params: Params, now_ms: int, consumption_w: Callable[[int], float],
             solar_map: dict, existing_schedule: Optional[dict] = None) -> PlanResult:
    P = params
    CAP = min(100.0, max(1.0, _num(P.capacity_kwh, 15.0)))
    MAXP = min(50.0, max(0.5, _num(P.max_power_kw, 9.0)))
    WEAR = max(0.0, P.wear_per_kwh or 0.0)
    KORT = P.feed_in_discount or 0.0
    MIN_MARGIN = max(0.0, _num(P.min_margin, 0.0))
    FLOOR = CAP * min(50.0, max(0.0, _num(P.min_soc_pct, 0.0))) / 100
    CAP = CAP - FLOOR                 # plannen op de bruikbare band boven de ondergrens
    START = max(0.0, (P.start_soc or 0.0) - FLOOR)
    zf = P.solar_factor
    if zf is None or (isinstance(zf, float) and math.isnan(zf)):
        zf = 0.0

    nu = (now_ms // BLOCK_MS) * BLOCK_MS

    running = None
    if existing_schedule:
        cur = existing_schedule.get(nu)
        prev = existing_schedule.get(nu - BLOCK_MS)
        ca = cur["action"] if cur else None
        pa = prev["action"] if prev else None
        if ca and pa and ca == pa and ca in ("laden", "ontladen"):
            running = ca

    n = len(hours)
    capacity = [MAXP * h["dur_h"] for h in hours]
    used_c = [0.0] * n
    used_d = [0.0] * n
    cum = [START] * (n + 1)

    solar_cap, self_cap = [], []
    for i, h in enumerate(hours):
        if h["key"] < nu:
            solar_cap.append(0.0)
            self_cap.append(0.0)
            continue
        zon = (solar_map.get(h["key"], 0) or 0) * zf
        verbruik = (consumption_w(h["key"]) / 1000) * h["dur_h"]
        solar_cap.append(max(0.0, min(capacity[i], zon - verbruik)))
        self_cap.append(max(0.0, min(capacity[i], verbruik - zon)))
    zon_totaal = sum(solar_cap)

    def verkoop_waarde(di):
        return hours[di]["price"] if used_d[di] < self_cap[di] - 0.0001 else hours[di]["price"] - KORT

    def laad_kosten(ci):
        return hours[ci]["price"] - KORT if used_c[ci] < solar_cap[ci] - 0.0001 else hours[ci]["price"]

    def herbereken():
        soc = START
        cum[0] = soc
        for i in range(n):
            soc += used_c[i] * ONEWAY - used_d[i] / ONEWAY
            cum[i + 1] = soc

    def gereserveerd(ci, di):
        som = 0.0
        for k in range(di):
            if k == ci or hours[k]["key"] < nu or used_d[k] > 0:
                continue
            som += max(0.0, solar_cap[k] - used_c[k])
        return som

    def max_charge(ci, di):
        max_ci = capacity[ci] - used_c[ci]
        zon_open = used_c[ci] < solar_cap[ci] - 0.0001
        if zon_open:
            max_ci = min(max_ci, solar_cap[ci] - used_c[ci])
        ruimte_di = capacity[di] - used_d[di]
        if used_d[di] < self_cap[di] - 0.0001:
            ruimte_di = min(ruimte_di, self_cap[di] - used_d[di])
        max_di = ruimte_di / RTE
        max_soc = -math.inf
        for k in range(ci + 1, di + 1):
            if cum[k] > max_soc:
                max_soc = cum[k]
        ruimte = CAP - max_soc
        door_ceiling = ruimte / ONEWAY if ruimte > 0 else 0.0
        if not zon_open:
            door_ceiling = max(0.0, door_ceiling - gereserveerd(ci, di))
        return min(max_ci, max_di, door_ceiling)

    def beste_paar():
        best = None
        for di in range(n):
            if used_d[di] >= capacity[di] or used_c[di] > 0:
                continue
            kand = []
            for ci in range(di):
                if hours[ci]["key"] < nu or used_c[ci] >= capacity[ci] or used_d[ci] > 0:
                    continue
                margin = verkoop_waarde(di) * RTE - laad_kosten(ci) - WEAR
                if margin <= MIN_MARGIN:
                    continue
                kand.append((ci, margin))
            if not kand:
                continue
            kand.sort(key=lambda x: -x[1])
            for ci, margin in kand:
                amount = max_charge(ci, di)
                if amount > 0.0001:
                    if best is None or margin > best[2]:
                        best = (ci, di, margin, amount)
                    break
        return best

    def beste_betaalde_marge(di):
        beste = -math.inf
        for ci in range(di):
            if hours[ci]["key"] < nu:
                continue
            kosten = (hours[ci]["price"] - KORT) if solar_cap[ci] > 0.0001 else hours[ci]["price"]
            m = (hours[di]["price"] - KORT) * RTE - kosten - WEAR
            if m > beste:
                beste = m
        return beste

    def verschuif_eigen_verbruik():
        """Nu het huis uit de batterij voeden en later goedkoop bijladen (ontladen VOOR laden).

        beste_paar kent alleen eerst-laden-dan-ontladen. Hier: voor elk kwartier i met nog niet
        gedekt eigen verbruik en elk later kwartier j om bij te laden, winst per geladen kWh
        = prijs(i) * RTE - laadkosten(j) - slijtage; alleen als dat boven de minimale winst ligt.
        De SoC mag tussen i en j niet onder 0 (bruikbare band) komen.
        """
        n_ok = 0
        for _ in range(3000):
            best = None
            for i in range(n):
                if hours[i]["key"] < nu or used_c[i] > 0:
                    continue
                d_max = min(self_cap[i] - used_d[i], capacity[i] - used_d[i])
                if d_max <= 0.0001:
                    continue
                low = math.inf
                for j in range(i + 1, n):
                    low = min(low, cum[j])           # cum[j] = SoC aan het begin van kwartier j
                    if hours[j]["key"] < nu or used_d[j] > 0 or used_c[j] >= capacity[j]:
                        continue
                    kosten = hours[j]["price"] - KORT if used_c[j] < solar_cap[j] - 0.0001 else hours[j]["price"]
                    margin = hours[i]["price"] * RTE - kosten - WEAR
                    if margin <= MIN_MARGIN:
                        continue
                    room_c = capacity[j] - used_c[j]
                    if used_c[j] < solar_cap[j] - 0.0001:
                        room_c = min(room_c, solar_cap[j] - used_c[j])
                    amount = min(d_max, room_c * RTE, low * ONEWAY)
                    if amount > 0.0001 and (best is None or margin > best[2]):
                        best = (i, j, margin, amount)
            if not best:
                break
            i, j, _, amount = best
            used_d[i] += amount
            used_c[j] += amount / RTE
            herbereken()
            n_ok += 1
        return n_ok

    def draai(modus):
        for i in range(n):
            used_c[i] = 0.0
            used_d[i] = 0.0
        herbereken()
        kand = []
        for i in range(n):
            if hours[i]["key"] < nu:
                continue
            marge_vrij = hours[i]["price"] * ONEWAY
            if marge_vrij <= 0:
                continue
            if modus == "A":
                betaald = max(beste_betaalde_marge(i), 0)
                voordeel = marge_vrij * ONEWAY - betaald
                zv = self_cap[i]
                if zv > 0.0001 and KORT:
                    kand.append((i, voordeel, zv))
                    kand.append((i, voordeel - KORT * ONEWAY, capacity[i] - zv))
                else:
                    kand.append((i, voordeel - (KORT * ONEWAY if KORT else 0.0), capacity[i]))
            else:
                # Voorraad verdelen: het deel dat het huis zelf verbruikt is de inkoopprijs waard
                # (geen terugleverkorting), de rest wordt tegen prijs min korting verkocht.
                zv = self_cap[i]
                if zv > 0.0001 and KORT:
                    kand.append((i, hours[i]["price"], zv))
                    kand.append((i, hours[i]["price"] - KORT, capacity[i] - zv))
                else:
                    kand.append((i, hours[i]["price"] - KORT, capacity[i]))
        kand.sort(key=lambda x: -x[1])
        rest = START * ONEWAY
        for i, _, cap_deel in kand:
            if rest <= 0.0001:
                break
            neem = min(cap_deel, capacity[i] - used_d[i], rest)
            if neem > 0:
                used_d[i] += neem
                rest -= neem
        herbereken()
        safety = 0
        while safety < 3000:
            safety += 1
            b = beste_paar()
            if not b:
                break
            ci, di, _, amount = b
            used_c[ci] += amount
            used_d[di] += amount * RTE
            herbereken()
        if P.shift_own_use:
            verschuif_eigen_verbruik()
        waarde = 0.0
        for i in range(n):
            dz = min(used_d[i], self_cap[i])
            waarde += dz * hours[i]["price"] + (used_d[i] - dz) * (hours[i]["price"] - KORT)
            zd = min(used_c[i], solar_cap[i])
            waarde -= zd * (hours[i]["price"] - KORT) + (used_c[i] - zd) * hours[i]["price"]
            waarde -= WEAR * used_c[i]
        return list(used_c), list(used_d), waarde, safety

    gekozen = draai("A")
    tekst = "A"
    if zon_totaal > 0.5:
        a = gekozen
        b = draai("B")
        if a[2] - b[2] > MIN_WINST_ZON_PLAN:
            gekozen = a
            tekst = f"A (+{a[2] - b[2]:.2f})"
        else:
            gekozen = b
            tekst = f"B (A scoort {a[2] - b[2]:.2f} beter)"
    for i in range(n):
        used_c[i] = gekozen[0][i]
        used_d[i] = gekozen[1][i]

    schedule = {}
    for i, h in enumerate(hours):
        if used_c[i] > 0:
            schedule[h["key"]] = {"action": "laden", "power_w": math.floor(used_c[i] / h["dur_h"] * 1000 + 0.5)}
        elif used_d[i] > 0:
            # self_w: het deel dat het eigen verbruik dekt; de aansturing volgt hier de echte afname
            eigen = min(used_d[i], self_cap[i])
            schedule[h["key"]] = {"action": "ontladen", "power_w": math.floor(used_d[i] / h["dur_h"] * 1000 + 0.5),
                                  "self_w": math.floor(eigen / h["dur_h"] * 1000 + 0.5)}
        else:
            schedule[h["key"]] = {"action": "idle", "power_w": 0}

    if running and nu in schedule and schedule[nu]["action"] != running and existing_schedule and nu in existing_schedule:
        schedule[nu] = existing_schedule[nu]

    return PlanResult(schedule=schedule, plan=tekst, solar_surplus_kwh=zon_totaal,
                      running_series=running, n_blocks=n, safety=gekozen[3],
                      charge=list(used_c), discharge=list(used_d))
