"""Dagarchief per kwartier: opsommen, historie omrekenen en dagoverzicht (pure Python, geen HA)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from .planner import AMS

QUARTER_MS = 900_000
RETENTION_DAYS = 730          # 2 jaar
MAX_DT_S = 10.0               # een tick-gat groter dan dit telt niet mee (herstart e.d.)

# Kolommen van een kwartierrij (volgorde = opslagvolgorde)
COLS = ["t", "price", "charge", "discharge", "house", "solar", "imp", "exp", "rev", "soc",
        "plan", "kind", "soc_plan", "reason", "charge_solar", "discharge_grid", "ev"]
IDX = {c: i for i, c in enumerate(COLS)}
REASON_MAX = 100
SOLAR_MAX_W = 20000.0         # alles daarbuiten is een foutwaarde van de omvormer (bijv. -536870.9 W)
EPS = 0.0005                  # kWh: onder deze waarde telt een kwartier als 'idle'


def val(row: list, col: str):
    """Waarde uit een rij; oudere rijen zonder deze kolom geven None."""
    i = IDX[col]
    return row[i] if i < len(row) else None


def quarter_start(ms: float) -> int:
    ms = int(ms)
    return ms - ms % QUARTER_MS


def day_of(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, AMS).strftime("%Y-%m-%d")


def month_of(day: str) -> str:
    return day[:7]


def _r(x: Optional[float], n: int = 4) -> Optional[float]:
    return None if x is None else round(float(x), n)


def classify(charge: float, discharge: float, charge_solar: float, discharge_grid: float) -> str:
    """Z = laden uit zon-overschot, N = laden van het net, H = ontladen naar huis, E = ontladen naar het net, I = idle."""
    if charge >= discharge and charge > EPS:
        return "Z" if charge_solar >= charge * 0.5 else "N"
    if discharge > EPS:
        return "E" if discharge_grid >= discharge * 0.5 else "H"
    return "I"


class QuarterAcc:
    """Verzamelt energie over één kwartier uit de 2-seconden-ticks."""

    def __init__(self, key: int, price: float, plan: Optional[str], soc_plan: Optional[float]) -> None:
        self.key = key
        self.price = price
        self.plan = plan
        self.soc_plan = soc_plan
        self.charge = self.discharge = self.house = self.solar = 0.0
        self.imp = self.exp = self.charge_solar = self.discharge_grid = 0.0
        self.ev = 0.0
        self.rev = 0.0
        self.soc: Optional[float] = None
        self.reason = ""
        self.last_total: Optional[float] = None
        self.seconds = 0.0

    def add(self, dt_s: float, out: dict, solar_w: Optional[float], ev_w: float = 0.0) -> None:
        if dt_s <= 0 or dt_s > MAX_DT_S:
            dt_s = 0.0
        f = dt_s / 3.6e6                                  # W * s -> kWh
        ch, di = out.get("charge_w") or 0.0, out.get("discharge_w") or 0.0
        house = out.get("house_w") or 0.0
        sol = solar_w if (solar_w is not None and 0.0 <= solar_w <= SOLAR_MAX_W) else 0.0
        exp = out.get("effective_export_w") or 0.0
        self.charge += ch * f
        self.discharge += di * f
        self.house += house * f
        self.solar += sol * f
        self.imp += (out.get("effective_import_w") or 0.0) * f
        self.exp += exp * f
        self.ev += max(0.0, ev_w or 0.0) * f
        self.charge_solar += min(ch, max(0.0, sol - house)) * f
        self.discharge_grid += min(di, exp) * f
        self.seconds += dt_s
        tot = out.get("revenue_total")
        if tot is not None:
            if self.last_total is not None:
                self.rev += tot - self.last_total
            self.last_total = tot
        if out.get("soc_kwh") is not None:
            self.soc = out["soc_kwh"]
        if out.get("reason"):
            self.reason = str(out["reason"])[:REASON_MAX]

    def to_row(self) -> list:
        kind = classify(self.charge, self.discharge, self.charge_solar, self.discharge_grid)
        return [self.key, _r(self.price, 5), _r(self.charge), _r(self.discharge), _r(self.house), _r(self.solar),
                _r(self.imp), _r(self.exp), _r(self.rev, 5), _r(self.soc, 3), self.plan, kind, _r(self.soc_plan, 3),
                self.reason, _r(self.charge_solar), _r(self.discharge_grid), _r(self.ev)]

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "QuarterAcc":
        a = cls(d["key"], d.get("price", 0.0), d.get("plan"), d.get("soc_plan"))
        a.__dict__.update(d)
        return a


# ---------------------------------------------------------------- historie (recorder) omrekenen
def _mean(points: list[tuple[int, float]], a: int, b: int) -> Optional[float]:
    """Tijdgewogen gemiddelde van een stapsgewijze reeks over [a, b)."""
    if not points or b <= a:
        return None
    v: Optional[float] = None
    i = 0
    while i < len(points) and points[i][0] <= a:
        v = points[i][1]
        i += 1
    cur, som, dek = a, 0.0, 0
    while i < len(points) and points[i][0] < b:
        if v is not None:
            som += v * (points[i][0] - cur)
            dek += points[i][0] - cur
        cur, v = points[i][0], points[i][1]
        i += 1
    if v is not None:
        som += v * (b - cur)
        dek += b - cur
    return som / dek if dek > 0 else None


def _last(points: list[tuple[int, float]], b: int) -> Optional[float]:
    v = None
    for t, x in points:
        if t <= b:
            v = x
        else:
            break
    return v


def _last_text(points: list[tuple[int, str]], b: int) -> str:
    v = ""
    for t, x in points:
        if t <= b:
            v = x
        else:
            break
    return v


def rows_from_history(num: dict[str, list[tuple[int, float]]], text: dict[str, list[tuple[int, str]]],
                      t0: int, t1: int) -> list[list]:
    """Bouw kwartierrijen uit recorder-reeksen (ms, waarde). Sleutels num: price, charge_w, discharge_w, house_w,
    solar_w, imp_w, exp_w, soc, rev_total. Kwartieren zonder vermogens- en SoC-data worden overgeslagen."""
    rows: list[list] = []
    t = quarter_start(t0)
    if t < t0:
        t += QUARTER_MS
    while t + QUARTER_MS <= t1:
        a, b = t, t + QUARTER_MS
        t += QUARTER_MS
        ch_w, di_w = _mean(num.get("charge_w", []), a, b), _mean(num.get("discharge_w", []), a, b)
        soc = _last(num.get("soc", []), b)
        if (ch_w is None and di_w is None) or soc is None:
            continue
        ch_w, di_w = ch_w or 0.0, di_w or 0.0
        house_w = _mean(num.get("house_w", []), a, b) or 0.0
        solar_w = _mean([(t_, v if 0.0 <= v <= SOLAR_MAX_W else 0.0) for t_, v in num.get("solar_w", [])], a, b) or 0.0
        exp_w = _mean(num.get("exp_w", []), a, b) or 0.0
        imp_w = _mean(num.get("imp_w", []), a, b) or 0.0
        k = 0.25 / 1000                                   # W gemiddeld over een kwartier -> kWh
        ch, di = ch_w * k, di_w * k
        chz = min(ch_w, max(0.0, solar_w - house_w)) * k
        dng = min(di_w, exp_w) * k
        ev = _mean(num["ev_w"], a, b) if num.get("ev_w") else None
        r0, r1 = _last(num.get("rev_total", []), a), _last(num.get("rev_total", []), b)
        price = _mean(num.get("price", []), a, b)
        rows.append([a, _r(price, 5), _r(ch), _r(di), _r(house_w * k), _r(solar_w * k), _r(imp_w * k), _r(exp_w * k),
                     _r((r1 - r0) if (r0 is not None and r1 is not None) else 0.0, 5), _r(soc, 3), None,
                     classify(ch, di, chz, dng), None, _last_text(text.get("reason", []), b)[:REASON_MAX], _r(chz), _r(dng),
                     None if ev is None else _r(max(0.0, ev) * k)])
    return rows


# ---------------------------------------------------------------- dagoverzicht
def day_view(rows: list[list], day: str) -> dict[str, Any]:
    """Totalen + reeksen voor één dag (rijen gesorteerd op tijd)."""
    rows = sorted((r for r in rows if day_of(r[0]) == day), key=lambda r: r[0])
    s = {c: 0.0 for c in ("charge", "discharge", "house", "solar", "imp", "exp", "rev", "charge_solar", "discharge_grid", "ev")}
    ev_bekend = 0
    prijzen = []
    cum, reeks = 0.0, []
    for r in rows:
        for c in s:
            s[c] += val(r, c) or 0.0
        if val(r, "ev") is not None:
            ev_bekend += 1
        if r[IDX["price"]] is not None:
            prijzen.append(r[IDX["price"]])
        cum += r[IDX["rev"]] or 0.0
        reeks.append([r[0], r[IDX["price"]], r[IDX["charge"]], r[IDX["discharge"]], r[IDX["house"]], r[IDX["solar"]],
                      r[IDX["imp"]], r[IDX["exp"]], round(cum, 4), r[IDX["soc"]], r[IDX["plan"]], r[IDX["kind"]],
                      r[IDX["soc_plan"]], val(r, "ev")])
    totals = {
        "opbrengst": round(s["rev"], 3),
        "geladen_kwh": round(s["charge"], 3),
        "geladen_zon_kwh": round(s["charge_solar"], 3),
        "ontladen_kwh": round(s["discharge"], 3),
        "ontladen_net_kwh": round(s["discharge_grid"], 3),
        "huisverbruik_kwh": round(s["house"], 3),
        "auto_kwh": round(s["ev"], 3) if ev_bekend else None,
        "huis_excl_auto_kwh": round(s["house"] - s["ev"], 3) if ev_bekend == len(rows) and rows else None,
        "zon_kwh": round(s["solar"], 3),
        "afname_kwh": round(s["imp"], 3),
        "teruglevering_kwh": round(s["exp"], 3),
        "prijs_gem": round(sum(prijzen) / len(prijzen), 4) if prijzen else None,
        "prijs_min": min(prijzen) if prijzen else None,
        "prijs_max": max(prijzen) if prijzen else None,
        "kwartieren": len(rows),
    }
    return {"datum": day, "totalen": totals,
            "kolommen": ["t", "prijs", "geladen", "ontladen", "huis", "zon", "afname", "terug", "opbrengst_cum", "soc",
                         "plan", "soort", "soc_plan", "auto"],
            "reeks": reeks}


def moment_row(rows: list[list], day: str, hhmm: str) -> Optional[list]:
    """Het kwartier dat het gekozen tijdstip bevat (HH:MM, lokale tijd)."""
    try:
        h, m = (int(x) for x in hhmm.split(":")[:2])
    except ValueError:
        return None
    for r in rows:
        if day_of(r[0]) != day:
            continue
        dt = datetime.fromtimestamp(r[0] / 1000, AMS)
        if dt.hour == h and dt.minute <= m < dt.minute + 15:
            return r
    return None


def solar_invalid(row: list) -> bool:
    """Rij met een onmogelijke zonwaarde (foutwaarde van de omvormer meegeteld)."""
    z = row[IDX["solar"]]
    return z is not None and (z < 0 or z > SOLAR_MAX_W / 1000 * 0.25)


def needs_repair(row: list) -> bool:
    """Rij die uit de recorder opnieuw opgebouwd moet worden: foute zon of nog geen autokolom."""
    return solar_invalid(row) or len(row) <= IDX["ev"]
