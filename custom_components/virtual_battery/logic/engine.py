"""Batterij-engine (port van Node-RED functie 'Batterij Engine (5s tick)', eb1a0000a4).

Pure Python, geen Home Assistant-afhankelijkheden. Eén aanroep van `engine_tick` komt overeen
met één tick (in Node-RED elke 2 s). Tijden zijn epoch-ms, vermogen in W, energie in kWh.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .messages import ev_label, msg
from .planner import AMS, BLOCK_MS, ONEWAY, RTE, make_consumption_fn

DT_H = 2 / 3600
NOODKLEP_UUR = 15
NOODKLEP_SOC_PCT = 40
AVOND_NACHT_VAN = 18
AVOND_NACHT_TOT = 7
OVERVLOED_DREMPEL = 1.3
SCHAARSTE_VANAF_UUR = 13


def num(v, default):
    """JS: `isNaN(parseFloat(v)) ? default : parseFloat(v)`."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(f) else f


def jsround(x: float) -> int:
    return math.floor(x + 0.5)


def fx(x: float, d: int) -> str:
    return f"{x:.{d}f}"


@dataclass
class Block:
    key: int            # start (epoch-ms)
    start_iso: str
    price: Optional[float]
    dur_h: float


@dataclass
class Inputs:
    now_ms: int
    strategy: str = "off"          # off | charge_now | discharge_now | zero_meter | price_optimization | hybrid
    ev_policy: str = "never"       # never | night_only | always
    lang: str = "nl"               # taal van de reden-tekst (nl | en)
    price: float = 0.0
    feed_in_discount: float = 0.0
    max_margin: float = 0.0
    grid_import_w: float = 0.0
    grid_export_w: float = 0.0
    wallconnector_kw: float = 0.0
    solar_w: float = 0.0
    solar_remaining_today_kwh: Optional[float] = None
    base_load_fallback_w: float = 400.0
    profile: Optional[list] = None          # 7 x 24 W, maandag = 0
    cap_kwh: float = 15.0
    min_soc_pct: float = 0.0       # SoC-ondergrens (% van capaciteit)
    max_kw: float = 9.0
    depreciation_per_cycle: float = 0.0
    ha_soc: float = 0.0
    ha_total: float = 0.0
    ha_today: float = 0.0
    ha_avgcost: float = 0.0
    blocks: list = field(default_factory=list)     # Block, alle uren/kwartieren (ook zonder prijs)
    schedule: dict = field(default_factory=dict)   # {ms: {"action","power_w"}}
    solar_map: dict = field(default_factory=dict)  # {ms: kWh}
    solar_factor: float = 0.0


@dataclass
class State:
    """Wat Node-RED in de flow-context bewaart tussen ticks."""
    soc: Optional[float] = None
    total: Optional[float] = None
    today: Optional[float] = None
    avgcost: Optional[float] = None
    schema_code: str = ""
    schema_code_ms: int = 0
    published_base_w: Optional[int] = None


def engine_tick(inp: Inputs, st: State) -> dict:
    CAP = min(100.0, max(1.0, num(inp.cap_kwh, 15)))
    MAXP = min(50.0, max(0.5, num(inp.max_kw, 9))) * 1000
    WEAR_CYCLUS = max(0.0, num(inp.depreciation_per_cycle, 0))
    WEAR_PER_KWH = WEAR_CYCLUS / CAP
    now = inp.now_ms
    nu_dt = datetime.fromtimestamp(now / 1000, AMS)
    huidig_uur = nu_dt.hour

    strategie = inp.strategy or "off"
    ev_beleid = inp.ev_policy or "never"
    lang = inp.lang
    ev_txt = ev_label(lang, ev_beleid)
    prijs = num(inp.price, 0)
    korting = num(inp.feed_in_discount, 0)
    max_marge = num(inp.max_margin, 0)
    import_price = prijs
    export_price = prijs - korting
    p1_afname = num(inp.grid_import_w, 0)
    p1_productie = num(inp.grid_export_w, 0)
    wallconnector = num(inp.wallconnector_kw, 0) * 1000

    zon_raw = num(inp.solar_w, float("nan"))
    zon_geldig = not math.isnan(zon_raw) and math.isfinite(zon_raw) and 0 <= zon_raw <= 20000
    zon = zon_raw if zon_geldig else 0
    zon_resterend = num(inp.solar_remaining_today_kwh, None)

    basis_helper_w = num(inp.base_load_fallback_w, 400)
    VP = inp.profile
    verbruik_w = make_consumption_fn(VP, basis_helper_w)
    basisverbruik_w = verbruik_w(now)

    ha_soc = num(inp.ha_soc, 0)
    soc_acc, tot_acc, dag_acc, avg_acc = st.soc, st.total, st.today, st.avgcost
    if soc_acc is None or abs(ha_soc - soc_acc) > 0.02:
        soc_acc = ha_soc
    if tot_acc is None or abs(num(inp.ha_total, 0) - tot_acc) > 0.005:
        tot_acc = num(inp.ha_total, 0)
    if dag_acc is None or abs(num(inp.ha_today, 0) - dag_acc) > 0.005:
        dag_acc = num(inp.ha_today, 0)
    if avg_acc is None or abs(num(inp.ha_avgcost, 0) - avg_acc) > 0.005:
        avg_acc = num(inp.ha_avgcost, 0)

    soc = soc_acc
    if soc > CAP:
        soc = CAP
    FLOOR = CAP * min(50.0, max(0.0, num(inp.min_soc_pct, 0))) / 100
    usable = max(0.0, soc - FLOOR)   # ontlaadbare energie boven de ondergrens
    opbrengst_totaal = tot_acc
    opbrengst_vandaag = dag_acc
    avg_cost = avg_acc

    power_w = 0.0
    reden = ""
    charge_cost_price = import_price

    huisverbruik_nu = max(0, zon + p1_afname - p1_productie)

    ZON_MAP = inp.solar_map or {}
    ZON_FACTOR = inp.solar_factor
    if ZON_FACTOR is None or (isinstance(ZON_FACTOR, float) and math.isnan(ZON_FACTOR)):
        ZON_FACTOR = 0

    def zon_kwh_blok(key):
        v = ZON_MAP.get(key)
        return (0 if v is None else v) * ZON_FACTOR

    def netto_verbruik_kwh(b):
        return max(0, (verbruik_w(b.key) / 1000) * b.dur_h - zon_kwh_blok(b.key))

    def effectieve_laadprijs(b):
        surplus = max(0, zon_kwh_blok(b.key) - (verbruik_w(b.key) / 1000) * b.dur_h)
        cap_kwh = (MAXP / 1000) * b.dur_h
        fr = min(1, surplus / cap_kwh) if cap_kwh > 0 else 0
        return (b.price or 0) - korting * fr

    priced = [b for b in inp.blocks if b.price is not None]

    def toekomst_blokken_prijs(vanaf_ms, hoog_eerst):
        bl = [b for b in priced if b.key >= vanaf_ms]
        bl = sorted(bl, key=lambda b: -b.price if hoog_eerst else b.price)
        return bl

    def marginale_verkoopprijs(kwh):
        bl = toekomst_blokken_prijs(now, True)
        if not bl:
            return None
        needed = kwh
        last = bl[0].price
        for b in bl:
            if needed <= 0:
                break
            needed -= (MAXP / 1000) * b.dur_h
            last = b.price
        return last

    def duurste_benodigde_laadprijs(headroom):
        bl = toekomst_blokken_prijs(now, False)
        if not bl:
            return None
        needed = headroom / ONEWAY if headroom > 0 else 0
        last = bl[0].price
        for b in bl:
            if needed <= 0:
                break
            needed -= (MAXP / 1000) * b.dur_h
            last = b.price
        return last

    def blokken_vanaf(huidig_key):
        out = []
        for b in sorted(priced, key=lambda b: b.key):
            if b.key >= huidig_key:
                out.append({"key": b.key, "start": b.key, "price": b.price, "dur_h": b.dur_h,
                            "plan": inp.schedule.get(b.key), "b": b})
        return out

    def marginale_verkoopprijs_binnen_horizon(soc_nu, huidig_key):
        vanaf = blokken_vanaf(huidig_key)
        volgend_laad = next((b["start"] for b in vanaf if b["plan"] and b["plan"]["action"] == "laden"), None)
        ontlaad = [b for b in vanaf if b["plan"] and b["plan"]["action"] == "ontladen"]
        voor = sorted([b for b in ontlaad if volgend_laad is None or b["start"] < volgend_laad], key=lambda b: -b["price"])
        na = sorted([b for b in ontlaad if volgend_laad is not None and b["start"] >= volgend_laad], key=lambda b: -b["price"])
        bl = voor + na
        if not bl:
            return None
        needed = soc_nu * ONEWAY
        last = bl[0]["price"]
        for b in bl:
            if needed <= 0:
                break
            needed -= (MAXP / 1000) * b["dur_h"]
            last = b["price"]
        return last

    def wacht_op_beter_moment(soc_nu, huidig_key):
        vanaf = blokken_vanaf(huidig_key)
        volgend_laad = next((b["start"] for b in vanaf if b["plan"] and b["plan"]["action"] == "laden"), None)
        kand = [b for b in vanaf if b["plan"] and b["plan"]["action"] == "ontladen"
                and (volgend_laad is None or b["start"] < volgend_laad)]
        if not kand:
            return {"wachten": False}
        ges = sorted(kand, key=lambda b: -b["price"])
        nodig = soc_nu * ONEWAY
        keys = set()
        for b in ges:
            if nodig <= 0:
                break
            keys.add(b["key"])
            nodig -= (MAXP / 1000) * b["dur_h"]
        return {"wachten": huidig_key not in keys, "beste_prijs": ges[0]["price"]}

    def wacht_op_beter_moment_hybride(soc_nu, huidig_key):
        vanaf = blokken_vanaf(huidig_key)
        volgend_laad = next((b["start"] for b in vanaf if b["plan"] and b["plan"]["action"] == "laden"), None)
        bieders = []
        for b in vanaf:
            if not (volgend_laad is None or b["start"] < volgend_laad):
                continue
            if b["plan"] and b["plan"]["action"] == "ontladen":
                bieders.append({"key": b["key"], "waarde": b["price"] - korting, "cap": (MAXP / 1000) * b["dur_h"], "verkoop": True})
            bieders.append({"key": "zv_%d" % b["key"], "waarde": b["price"], "cap": netto_verbruik_kwh(b["b"]), "verkoop": False})
        if not bieders:
            return {"wachten": False}
        bieders.sort(key=lambda x: -x["waarde"])
        voorraad = soc_nu * ONEWAY
        mag_nu = False
        for bod in bieders:
            if voorraad <= 0.0001:
                break
            genomen = min(bod["cap"], voorraad)
            if bod["verkoop"] and bod["key"] == huidig_key:
                mag_nu = True
            voorraad -= genomen
        return {"wachten": not mag_nu}

    def wacht_op_goedkoper_laadmoment(soc_nu, huidig_key):
        vanaf = blokken_vanaf(huidig_key)
        volgend_ontlaad = next((b["start"] for b in vanaf if b["plan"] and b["plan"]["action"] == "ontladen"), None)
        kand = [b for b in vanaf if b["plan"] and b["plan"]["action"] == "laden"
                and (volgend_ontlaad is None or b["start"] < volgend_ontlaad)]
        if not kand:
            return {"wachten": False}
        ges = sorted(kand, key=lambda b: effectieve_laadprijs(b["b"]))
        headroom = CAP - soc_nu
        nodig = headroom / ONEWAY if headroom > 0 else 0
        keys = set()
        for b in ges:
            if nodig <= 0:
                break
            keys.add(b["key"])
            nodig -= (MAXP / 1000) * b["dur_h"]
        return {"wachten": huidig_key not in keys, "beste_prijs": ges[0]["price"]}

    def bereken_schema_code():
        alle = inp.blocks
        if not alle:
            return ""
        blokken = []
        for b in alle:
            plan = inp.schedule.get(b.key)
            blokken.append({"t": b.key, "price": b.price or 0, "dur_h": b.dur_h,
                            "actie": plan["action"] if plan else "idle", "b": b})
        i0 = next((i for i, b in enumerate(blokken) if b["t"] >= now), -1)
        if i0 < 0:
            return ""
        sim_soc = soc
        uit = ["I"] * len(blokken)
        for i in range(i0, len(blokken)):
            b = blokken[i]
            if b["actie"] == "laden":
                volgend_ontlaad = next((blokken[j]["t"] for j in range(i, len(blokken)) if blokken[j]["actie"] == "ontladen"), None)
                kand = [j for j in range(i, len(blokken)) if blokken[j]["actie"] == "laden"
                        and (volgend_ontlaad is None or blokken[j]["t"] < volgend_ontlaad)]
                ges = sorted(kand, key=lambda j: effectieve_laadprijs(blokken[j]["b"]))
                headroom_t = CAP - sim_soc
                nodig = headroom_t / ONEWAY if headroom_t > 0 else 0
                ben = set()
                for j in ges:
                    if nodig <= 0:
                        break
                    ben.add(j)
                    nodig -= (MAXP / 1000) * blokken[j]["dur_h"]
                if i in ben:
                    headroom = CAP - sim_soc
                    kw = min(MAXP / 1000, headroom / (ONEWAY * b["dur_h"]) if headroom > 0 else 0)
                    sim_soc = min(CAP, sim_soc + kw * b["dur_h"] * ONEWAY)
                    uit[i] = "L" if kw > 0.05 else "I"
            elif b["actie"] == "ontladen":
                volgend_laad = next((blokken[j]["t"] for j in range(i, len(blokken)) if blokken[j]["actie"] == "laden"), None)
                kand = [j for j in range(i, len(blokken)) if blokken[j]["actie"] == "ontladen"
                        and (volgend_laad is None or blokken[j]["t"] < volgend_laad)]
                ges = sorted(kand, key=lambda j: -blokken[j]["price"])
                nodig = max(0, sim_soc - FLOOR) * ONEWAY
                ben = set()
                for j in ges:
                    if nodig <= 0:
                        break
                    ben.add(j)
                    nodig -= (MAXP / 1000) * blokken[j]["dur_h"]
                if i in ben:
                    kw = min(MAXP / 1000, (max(0, sim_soc - FLOOR) * ONEWAY) / b["dur_h"] if sim_soc > FLOOR else 0)
                    sim_soc = max(FLOOR, sim_soc - kw * b["dur_h"] / ONEWAY)
                    uit[i] = "O" if kw > 0.05 else "I"
        return alle[0].start_iso + ";" + "".join(uit)

    soc_procent_nu = (soc / CAP) * 100
    noodklep = huidig_uur >= NOODKLEP_UUR and soc_procent_nu < NOODKLEP_SOC_PCT
    profitable = usable > 0.001 and avg_cost < (import_price * ONEWAY)
    in_avond_nacht = huidig_uur >= AVOND_NACHT_VAN or huidig_uur < AVOND_NACHT_TOT
    if ev_beleid == "never":
        ev_toegestaan = False
    elif ev_beleid == "night_only":
        ev_toegestaan = in_avond_nacht and profitable
    else:
        ev_toegestaan = profitable

    if strategie == "charge_now":
        charge_cost_price = import_price
        headroom = CAP - soc
        kw = min(MAXP / 1000, headroom / (ONEWAY * DT_H) if headroom > 0 else 0)
        power_w = max(0, kw) * 1000
        reden = msg(lang, "manual_charge", w=jsround(power_w)) if power_w > 1 else msg(lang, "manual_charge_full")
    elif strategie == "discharge_now":
        kw = min(MAXP / 1000, (usable * ONEWAY) / DT_H if usable > 0 else 0)
        power_w = -max(0, kw) * 1000
        reden = msg(lang, "manual_discharge", w=jsround(-power_w)) if power_w < -1 else msg(lang, "manual_discharge_empty")
    elif strategie == "off":
        reden = msg(lang, "off")
    elif strategie == "zero_meter":
        headroom_nu = CAP - soc
        overvloed = None
        schaars = False
        if zon_resterend is not None and headroom_nu > 0.01:
            overvloed = zon_resterend / headroom_nu
            schaars = overvloed <= OVERVLOED_DREMPEL and huidig_uur >= SCHAARSTE_VANAF_UUR
        verwachte_voorraad = min(CAP, soc + max(0, zon_resterend)) if zon_resterend is not None else soc
        marginale = marginale_verkoopprijs(verwachte_voorraad)
        vereiste = max_marge * (soc_procent_nu / 100)
        if marginale is None:
            charge_allowed = True
            marge_uitleg = msg(lang, "no_price_data")
        else:
            marge = marginale - export_price
            charge_allowed = marge >= vereiste
            marge_uitleg = msg(lang, "margin_explain", stock=fx(verwachte_voorraad, 1), marginal=fx(marginale, 3), now=fx(export_price, 3),
                               margin=fx(marge, 3), required=fx(vereiste, 3), soc=fx(soc_procent_nu, 0))
        override = None
        if noodklep:
            charge_allowed = True
            override = msg(lang, "override_emergency")
        elif schaars:
            charge_allowed = True
            override = msg(lang, "override_scarcity", solar=fx(zon_resterend, 1), room=fx(headroom_nu, 1), factor=fx(overvloed, 2),
                           hour=str(SCHAARSTE_VANAF_UUR))
        if p1_productie > 1:
            if not charge_allowed:
                reden = msg(lang, "idle_prefer_feed_in", explain=marge_uitleg,
                            extra=msg(lang, "overflow_factor", factor=fx(overvloed, 2)) if overvloed is not None else "")
            else:
                charge_cost_price = export_price
                kw = min(MAXP / 1000, p1_productie / 1000, headroom_nu / (ONEWAY * DT_H) if headroom_nu > 0 else 0)
                power_w = max(0, kw) * 1000
                reden = msg(lang, "charge_with_reason", w=jsround(power_w), why=(override or marge_uitleg)) if power_w > 1 else msg(lang, "idle_surplus_small")
        else:
            ev_laadt = wallconnector > 1
            afname_dekken = max(0, p1_afname - wallconnector) if (ev_laadt and not ev_toegestaan) else p1_afname
            if afname_dekken > 1:
                kw = min(MAXP / 1000, afname_dekken / 1000, (usable * ONEWAY) / DT_H if usable > 0 else 0)
                power_w = -max(0, kw) * 1000
                if power_w < -1:
                    reden = msg(lang, "discharge_cover_ev", w=jsround(-power_w), ev=ev_txt) if ev_laadt \
                        else msg(lang, "discharge_cover_house", w=jsround(-power_w))
                else:
                    reden = msg(lang, "idle_empty_cannot_cover")
            elif ev_laadt:
                reden = msg(lang, "idle_ev_no_supply", ev=ev_txt)
            else:
                reden = msg(lang, "idle_balanced")
    elif strategie in ("price_optimization", "hybrid"):
        schedule = inp.schedule or {}
        hour_key = (now // BLOCK_MS) * BLOCK_MS
        plan = schedule.get(hour_key)
        ev_laadt = wallconnector > 1
        afname_dekken = max(0, p1_afname - wallconnector) if (ev_laadt and not ev_toegestaan) else p1_afname
        is_hybride = strategie == "hybrid"
        res = {"p": 0.0, "r": ""}   # gedeeld met de hulpfuncties
        cc = {"v": charge_cost_price}

        def pak_zelfverbruik(context):
            if not is_hybride or afname_dekken <= 1 or usable <= 0.001:
                return False
            marginale = marginale_verkoopprijs_binnen_horizon(usable, hour_key)
            netto_later = (marginale - korting) if marginale is not None else -math.inf
            if import_price <= netto_later:
                return False
            kw = min(MAXP / 1000, afname_dekken / 1000, (usable * ONEWAY) / DT_H if usable > 0 else 0)
            res["p"] = -max(0, kw) * 1000
            if res["p"] < -1:
                vergelijk = msg(lang, "self_use_cheaper", net=fx(netto_later, 3)) if marginale is not None \
                    else msg(lang, "self_use_no_alt")
                res["r"] = msg(lang, "self_use_now", w=jsround(-res["p"]), price=fx(import_price, 3), compare=vergelijk, context=context,
                               excl_ev=msg(lang, "excl_ev") if ev_laadt else "")
                return True
            return False

        def zon_overschot_opslag():
            """(vermogen in W, drempelprijs) als het huidige zonoverschot opslaan loont, anders None."""
            if not is_hybride or p1_productie <= 1:
                return None
            headroom = CAP - soc
            if headroom <= 0.01:
                return None
            drempel = duurste_benodigde_laadprijs(headroom)
            if drempel is None:
                return None
            waarde_opslaan = drempel * ONEWAY - WEAR_PER_KWH
            if waarde_opslaan <= export_price:
                return None
            kw = min(MAXP / 1000, p1_productie / 1000, headroom / (ONEWAY * DT_H))
            return max(0, kw) * 1000, drempel

        def pak_zon_overschot(context):
            opslag = zon_overschot_opslag()
            if opslag is None:
                return False
            cc["v"] = export_price
            res["p"] = opslag[0]
            if res["p"] > 1:
                res["r"] = msg(lang, "store_surplus", w=jsround(res["p"]), threshold=fx(opslag[1], 3), price=fx(export_price, 3), context=context)
                return True
            return False

        if plan and plan["action"] == "ontladen":
            if ev_laadt and not ev_toegestaan:
                res["r"] = msg(lang, "idle_plan_discharge_ev", ev=ev_txt)
            else:
                wacht = wacht_op_beter_moment_hybride(usable, hour_key) if is_hybride else wacht_op_beter_moment(usable, hour_key)
                if not wacht["wachten"]:
                    plan_w = plan["power_w"]
                    eigen_w = plan.get("self_w")
                    if eigen_w is not None and eigen_w > 0:
                        # kwartier met eigen verbruik uit de batterij: het eigen-verbruik-deel volgt de echte afname van
                        # het huis (boven of onder het profiel, tot het max. vermogen); het verkoopdeel blijft zoals gepland
                        plan_w = max(0, afname_dekken) + max(0, plan_w - eigen_w)
                    kw = min(plan_w / 1000, MAXP / 1000, (usable * ONEWAY) / DT_H if usable > 0 else 0)
                    res["p"] = -max(0, kw) * 1000
                    if res["p"] < -1:
                        res["r"] = msg(lang, "discharge_best_moment", w=jsround(-res["p"]),
                                       hybrid=msg(lang, "hybrid_expected_use", base=fx(basisverbruik_w, 0)) if is_hybride else "",
                                       ev_part=msg(lang, "ev_charges_along", ev=ev_txt) if ev_laadt else "")
                    else:
                        res["r"] = msg(lang, "idle_empty")
                elif not pak_zelfverbruik(msg(lang, "ctx_reserved")) \
                        and not pak_zon_overschot(msg(lang, "ctx_wait_better_sale")):
                    res["r"] = msg(lang, "idle_reserved", base=fx(basisverbruik_w, 0))
        elif plan and plan["action"] == "laden":
            wacht = wacht_op_goedkoper_laadmoment(soc, hour_key)
            if not wacht["wachten"]:
                headroom = CAP - soc
                kw = min(plan["power_w"] / 1000, MAXP / 1000, headroom / (ONEWAY * DT_H) if headroom > 0 else 0)
                res["p"] = max(0, kw) * 1000
                # Het geplande vermogen is een minimum voor het zondeel: is er meer zonoverschot dan gepland
                # (prognose te laag, nowcast, wolkengat) en loont opslaan, dan gaat het hele overschot de batterij in.
                opslag = zon_overschot_opslag()
                if opslag is not None and opslag[0] > res["p"]:
                    res["p"] = opslag[0]
                zon_deel = min(1, max(0, p1_productie) / res["p"]) if res["p"] > 1 else 0
                cc["v"] = zon_deel * export_price + (1 - zon_deel) * import_price
                if res["p"] > 1:
                    res["r"] = msg(lang, "charge_cheapest", w=jsround(res["p"]), price=fx(import_price, 3),
                                   solar_part=msg(lang, "solar_part", pct=jsround(zon_deel * 100)) if zon_deel > 0.05 else "")
                else:
                    res["r"] = msg(lang, "idle_full")
            elif not pak_zelfverbruik(msg(lang, "ctx_wait_cheaper_charge")) \
                    and not pak_zon_overschot(msg(lang, "ctx_wait_cheaper_charge")):
                bp = wacht.get("beste_prijs")
                res["r"] = msg(lang, "idle_wait_cheaper", price=(fx(bp, 3) if bp is not None else "?"))
        elif pak_zelfverbruik(""):
            pass
        elif pak_zon_overschot(""):
            pass
        elif not plan or plan["action"] == "idle":
            res["r"] = msg(lang, "idle_not_profitable", extra=(
                msg(lang, "extra_self_use_not_better") if (is_hybride and afname_dekken > 1)
                else (msg(lang, "extra_prefer_feed_in") if (is_hybride and p1_productie > 1) else "")))
        power_w = res["p"]
        reden = res["r"]
        charge_cost_price = cc["v"]
    else:
        reden = msg(lang, "unknown_strategy", strategy=strategie)

    energy_terminal = abs(power_w) / 1000 * DT_H
    if power_w > 0:
        stored = energy_terminal * ONEWAY
        nieuwe_soc = min(CAP, soc + stored)
        nieuw_bruikbaar = max(0.0, nieuwe_soc - FLOOR)
        if nieuw_bruikbaar > 0.0001:
            avg_cost = (usable * avg_cost + energy_terminal * charge_cost_price) / nieuw_bruikbaar
        soc = nieuwe_soc
    elif power_w < 0:
        removed = min(usable, energy_terminal / ONEWAY) if usable > 0 else 0
        soc = max(0, soc - removed)
        if soc - FLOOR <= 0.0001:
            avg_cost = 0
            soc = FLOOR if FLOOR > 0 else 0

    real_net = p1_afname - p1_productie
    eff_net = real_net + power_w
    eff_afname = max(0, eff_net)
    eff_productie = max(0, -eff_net)
    zonder_imp = max(0, real_net) / 1000 * DT_H
    zonder_exp = max(0, -real_net) / 1000 * DT_H
    cost_zonder = import_price * zonder_imp - export_price * zonder_exp
    met_imp = eff_afname / 1000 * DT_H
    met_exp = eff_productie / 1000 * DT_H
    cost_met = import_price * met_imp - export_price * met_exp
    delta = cost_zonder - cost_met
    opbrengst_totaal += delta
    opbrengst_vandaag += delta

    st.soc, st.total, st.today, st.avgcost = soc, opbrengst_totaal, opbrengst_vandaag, avg_cost

    soc_procent = (soc / CAP) * 100
    gecombineerd = power_w + wallconnector
    laad = power_w if power_w > 0 else 0
    ontlaad = -power_w if power_w < 0 else 0
    verreken = (-delta / energy_terminal) if energy_terminal > 0.00001 else 0

    schema_code = st.schema_code
    if now - st.schema_code_ms > 55000:
        schema_code = bereken_schema_code()
        st.schema_code = schema_code
        st.schema_code_ms = now

    nieuw_basis = None
    if VP:
        prof = jsround(basisverbruik_w)
        if st.published_base_w != prof:
            st.published_base_w = prof
            nieuw_basis = prof

    r3 = lambda x: jsround(x * 1000) / 1000
    return {
        "soc_kwh": r3(soc),
        "soc_pct": jsround(soc_procent * 100) / 100,
        "power_w": jsround(power_w),
        "combined_w": jsround(gecombineerd),
        "reason": reden,
        "revenue_today": r3(opbrengst_vandaag),
        "revenue_total": r3(opbrengst_totaal),
        "effective_import_w": jsround(eff_afname),
        "effective_export_w": jsround(eff_productie),
        "house_w": jsround(huisverbruik_nu),
        "charge_w": jsround(laad),
        "discharge_w": jsround(ontlaad),
        "avg_cost": r3(avg_cost),
        "settle_price": r3(verreken),
        "schema_code": schema_code,
        "base_load_w": nieuw_basis,
    }
