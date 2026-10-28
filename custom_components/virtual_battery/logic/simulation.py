"""Verwachte-opbrengst simulatie (port van Node-RED functie 'Verwachte opbrengst berekenen', eb1a0000vo2).

Vooruit-simulatie per kwartier van de engine-beslisregels (gespiegeld uit engine.py). Pure Python.
LET OP: in de uiteindelijke integratie moeten engine en simulatie dezelfde beslisregels delen
(nu nog een letterlijke kopie, net als in Node-RED).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .planner import AMS, ONEWAY, make_consumption_fn
from .engine import num, NOODKLEP_UUR, NOODKLEP_SOC_PCT, OVERVLOED_DREMPEL, SCHAARSTE_VANAF_UUR


@dataclass
class SimBlock:
    key: int
    end_ms: int
    price: float
    dur_h: float
    plan: Optional[dict] = None

    @property
    def start_ms(self):
        return self.key


@dataclass
class SimInputs:
    now_ms: int
    strategy: str
    feed_in_discount: float
    max_margin: float
    soc_kwh: float
    realised_today: float
    cap_kwh: float
    max_power_w: float
    wear_per_kwh: float
    profile: Optional[list]
    base_load_fallback_w: float
    solar_map: dict
    solar_factor: float
    blocks: list                    # SimBlock (alleen blokken met prijs, gesorteerd)
    tomorrow_valid: bool = True
    min_soc_pct: float = 0.0


def r3(x):
    return math.floor(x * 1000 + 0.5) / 1000


def _local(ms):
    dt = datetime.fromtimestamp(ms / 1000, AMS)
    return dt.hour, dt.strftime("%Y-%m-%d")


def simulate(inp: SimInputs) -> dict:
    CAP = min(100.0, max(1.0, num(inp.cap_kwh, 15) or 15))
    MAXP = min(50000.0, max(500.0, num(inp.max_power_w, 9000) or 9000))
    WEAR = max(0.0, num(inp.wear_per_kwh, 0) or 0)
    korting = inp.feed_in_discount
    max_marge = inp.max_margin
    strategie = inp.strategy
    soc = min(CAP, max(0.0, inp.soc_kwh))
    FLOOR = CAP * min(50.0, max(0.0, num(inp.min_soc_pct, 0))) / 100
    gerealiseerd = inp.realised_today
    ZF = inp.solar_factor if inp.solar_factor is not None and not (isinstance(inp.solar_factor, float) and math.isnan(inp.solar_factor)) else 0
    ZON = inp.solar_map or {}
    verbruik_w = make_consumption_fn(inp.profile, inp.base_load_fallback_w)
    alle = inp.blocks

    def zon_ruw(key):
        v = ZON.get(key)
        return 0 if v is None else v

    def zon_blok(key):
        return zon_ruw(key) * ZF

    def netto_verbruik_kwh(b):
        return max(0, (verbruik_w(b.key) / 1000) * b.dur_h - zon_blok(b.key))

    def eff_laadprijs(b):
        surplus = max(0, zon_blok(b.key) - (verbruik_w(b.key) / 1000) * b.dur_h)
        cap_kwh = (MAXP / 1000) * b.dur_h
        fr = min(1, surplus / cap_kwh) if cap_kwh > 0 else 0
        return b.price - korting * fr

    def vanaf_blok(key):
        return [b for b in alle if b.start_ms >= key]

    def na_moment(t):
        return [b for b in alle if b.start_ms > t]

    def marginale_verkoopprijs(kwh, t):
        bl = sorted(((b.price, (MAXP / 1000) * b.dur_h) for b in na_moment(t)), key=lambda x: -x[0])
        if not bl:
            return None
        needed, last = kwh, bl[0][0]
        for p, c in bl:
            if needed <= 0:
                break
            needed -= c
            last = p
        return last

    def duurste_laadprijs(head, t):
        bl = sorted(((b.price, (MAXP / 1000) * b.dur_h) for b in na_moment(t)), key=lambda x: x[0])
        if not bl:
            return None
        needed, last = (head / ONEWAY if head > 0 else 0), bl[0][0]
        for p, c in bl:
            if needed <= 0:
                break
            needed -= c
            last = p
        return last

    def volgende_actie_ms(vanaf, actie):
        for b in vanaf:
            if b.plan and b.plan["action"] == actie:
                return b.start_ms
        return None

    def marg_binnen_horizon(soc_nu, key):
        vanaf = vanaf_blok(key)
        laad_ms = volgende_actie_ms(vanaf, "laden")
        ontlaad = [b for b in vanaf if b.plan and b.plan["action"] == "ontladen"]
        voor = sorted([b for b in ontlaad if laad_ms is None or b.start_ms < laad_ms], key=lambda b: -b.price)
        na = sorted([b for b in ontlaad if laad_ms is not None and b.start_ms >= laad_ms], key=lambda b: -b.price)
        bl = voor + na
        if not bl:
            return None
        needed, last = soc_nu * ONEWAY, bl[0].price
        for b in bl:
            if needed <= 0:
                break
            needed -= (MAXP / 1000) * b.dur_h
            last = b.price
        return last

    def wacht_beter(soc_nu, key):
        vanaf = vanaf_blok(key)
        laad_ms = volgende_actie_ms(vanaf, "laden")
        kand = [b for b in vanaf if b.plan and b.plan["action"] == "ontladen" and (laad_ms is None or b.start_ms < laad_ms)]
        if not kand:
            return False
        ges = sorted(kand, key=lambda b: -b.price)
        nodig, keys = soc_nu * ONEWAY, set()
        for b in ges:
            if nodig <= 0:
                break
            keys.add(b.key)
            nodig -= (MAXP / 1000) * b.dur_h
        return key not in keys

    def wacht_beter_hybride(soc_nu, key):
        vanaf = vanaf_blok(key)
        laad_ms = volgende_actie_ms(vanaf, "laden")
        bieders = []
        for b in vanaf:
            if not (laad_ms is None or b.start_ms < laad_ms):
                continue
            if b.plan and b.plan["action"] == "ontladen":
                bieders.append((b.key, b.price - korting, (MAXP / 1000) * b.dur_h, True))
            bieders.append(("zv_%d" % b.key, b.price, netto_verbruik_kwh(b), False))
        if not bieders:
            return False
        bieders.sort(key=lambda x: -x[1])
        voorraad, mag_nu = soc_nu * ONEWAY, False
        for k, _, cap, verkoop in bieders:
            if voorraad <= 0.0001:
                break
            if verkoop and k == key:
                mag_nu = True
            voorraad -= min(cap, voorraad)
        return not mag_nu

    def wacht_goedkoper(soc_nu, key):
        vanaf = vanaf_blok(key)
        ontlaad_ms = volgende_actie_ms(vanaf, "ontladen")
        kand = [b for b in vanaf if b.plan and b.plan["action"] == "laden" and (ontlaad_ms is None or b.start_ms < ontlaad_ms)]
        if not kand:
            return False
        ges = sorted(kand, key=eff_laadprijs)
        head = CAP - soc_nu
        nodig, keys = (head / ONEWAY if head > 0 else 0), set()
        for b in ges:
            if nodig <= 0:
                break
            keys.add(b.key)
            nodig -= (MAXP / 1000) * b.dur_h
        return key not in keys

    def zon_resterend_dag(b):
        dag = _local(b.start_ms)[1]
        return sum(zon_ruw(k) for k in ZON if k >= b.start_ms and _local(k)[1] == dag)

    def beslis(b, dH, afname_w, productie_w):
        nonlocal soc
        import_price = b.price
        export_price = b.price - korting
        uur = _local(b.start_ms)[0]
        head = CAP - soc
        laad_max_kw = head / (ONEWAY * dH) if head > 0 else 0
        usable = max(0.0, soc - FLOOR)
        ontlaad_max_kw = (usable * ONEWAY) / dH if usable > 0 else 0
        p = {"w": 0.0}
        if strategie == "charge_now":
            p["w"] = max(0, min(MAXP / 1000, laad_max_kw)) * 1000
        elif strategie == "discharge_now":
            p["w"] = -max(0, min(MAXP / 1000, ontlaad_max_kw)) * 1000
        elif strategie == "zero_meter":
            soc_pct = (soc / CAP) * 100
            zon_rest = zon_resterend_dag(b)
            schaars = False
            if head > 0.01:
                schaars = (zon_rest / head <= OVERVLOED_DREMPEL) and (uur >= SCHAARSTE_VANAF_UUR)
            mp = marginale_verkoopprijs(min(CAP, soc + max(0, zon_rest)), b.start_ms)
            toegestaan = True if mp is None else (mp - export_price) >= max_marge * (soc_pct / 100)
            if (uur >= NOODKLEP_UUR and soc_pct < NOODKLEP_SOC_PCT) or schaars:
                toegestaan = True
            if productie_w > 1:
                if toegestaan:
                    p["w"] = max(0, min(MAXP / 1000, productie_w / 1000, laad_max_kw)) * 1000
            elif afname_w > 1:
                p["w"] = -max(0, min(MAXP / 1000, afname_w / 1000, ontlaad_max_kw)) * 1000
        elif strategie in ("price_optimization", "hybrid"):
            is_hybride = strategie == "hybrid"
            plan = b.plan

            def pak_zelfverbruik():
                if not is_hybride or afname_w <= 1 or usable <= 0.001:
                    return False
                mp = marg_binnen_horizon(usable, b.key)
                netto_later = (mp - korting) if mp is not None else -math.inf
                if import_price <= netto_later:
                    return False
                p["w"] = -max(0, min(MAXP / 1000, afname_w / 1000, ontlaad_max_kw)) * 1000
                return p["w"] < -1

            def pak_zon_overschot():
                if not is_hybride or productie_w <= 1 or head <= 0.01:
                    return False
                drempel = duurste_laadprijs(head, b.start_ms)
                if drempel is None:
                    return False
                if drempel * ONEWAY - WEAR <= export_price:
                    return False
                p["w"] = max(0, min(MAXP / 1000, productie_w / 1000, laad_max_kw)) * 1000
                return p["w"] > 1

            if plan and plan["action"] == "ontladen":
                w = wacht_beter_hybride(usable, b.key) if is_hybride else wacht_beter(usable, b.key)
                if not w:
                    p["w"] = -max(0, min(plan["power_w"] / 1000, MAXP / 1000, ontlaad_max_kw)) * 1000
                elif not pak_zelfverbruik():
                    pak_zon_overschot()
            elif plan and plan["action"] == "laden":
                w = wacht_goedkoper(soc, b.key)
                if not w:
                    p["w"] = max(0, min(plan["power_w"] / 1000, MAXP / 1000, laad_max_kw)) * 1000
                elif not pak_zelfverbruik():
                    pak_zon_overschot()
            elif not pak_zelfverbruik():
                pak_zon_overschot()
        return p["w"]

    nu = inp.now_ms
    cum = gerealiseerd
    dag = _local(nu)[1]
    reeks = [[nu, r3(cum)]]
    soc_reeks = [[nu, r3(soc)]]
    verwacht_vandaag = None
    laatste_morgen = None
    geladen = ontladen = 0.0
    ontlaad_split, laad_split = [], []

    for b in alle:
        if b.end_ms <= nu:
            continue
        s = max(b.start_ms, nu)
        fr = (b.end_ms - s) / (b.end_ms - b.start_ms)
        dH = b.dur_h * fr
        if dH <= 0:
            continue
        b_dag = _local(b.start_ms)[1]
        if b_dag != dag:
            if verwacht_vandaag is None:
                verwacht_vandaag = cum
            reeks.append([b.start_ms, None])
            cum = 0
            reeks.append([b.start_ms + 1, 0])
            dag = b_dag
        zon_kwh = zon_blok(b.key) * fr
        verbruik_kwh = (verbruik_w(b.key) / 1000) * dH
        net_kwh = verbruik_kwh - zon_kwh
        afname_w = max(0, net_kwh) / dH * 1000
        productie_w = max(0, -net_kwh) / dH * 1000
        power_w = beslis(b, dH, afname_w, productie_w)
        e_kwh = abs(power_w) / 1000 * dH
        if power_w > 0:
            soc = min(CAP, soc + e_kwh * ONEWAY)
            geladen += e_kwh
            if e_kwh > 0.005:
                zon_laad = min(e_kwh, max(0, -net_kwh))
                laad_split.append([b.start_ms, r3(zon_laad), r3(e_kwh - zon_laad)])
        elif power_w < 0:
            soc = max(0, soc - min(max(0.0, soc - FLOOR), e_kwh / ONEWAY))
            ontladen += e_kwh
            if e_kwh > 0.005:
                huis = min(e_kwh, max(0, net_kwh))
                ontlaad_split.append([b.start_ms, r3(huis), r3(e_kwh - huis)])
        imp, exp = b.price, b.price - korting
        eff_net = net_kwh + power_w / 1000 * dH
        zonder = imp * max(0, net_kwh) - exp * max(0, -net_kwh)
        met = imp * max(0, eff_net) - exp * max(0, -eff_net)
        cum += zonder - met
        reeks.append([b.end_ms, r3(cum)])
        soc_reeks.append([b.end_ms, r3(soc)])
        if verwacht_vandaag is not None:
            laatste_morgen = cum
    if verwacht_vandaag is None:
        verwacht_vandaag = cum

    return {
        "state": r3(verwacht_vandaag),
        "reeks": reeks, "soc_reeks": soc_reeks,
        "ontlaad_split": ontlaad_split, "laad_split": laad_split,
        "gerealiseerd_tot_nu": r3(gerealiseerd),
        "verwacht_vandaag": r3(verwacht_vandaag),
        "verwacht_morgen": r3(laatste_morgen) if (inp.tomorrow_valid and laatste_morgen is not None) else None,
        "verwacht_geladen_kwh": math.floor(geladen * 10 + 0.5) / 10,
        "verwacht_ontladen_kwh": math.floor(ontladen * 10 + 0.5) / 10,
    }
