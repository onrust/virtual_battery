"""Zelfverbruik buiten het plan: alleen uit voorraad die het plan niet nodig heeft, en alleen als het beter is dan de
beste latere toepassing (verkoop of zelfverbruik, tegen de marktprijs van dat kwartier)."""
from datetime import datetime, timedelta

from custom_components.virtual_battery.logic.engine import AMS, Block, Inputs, State, engine_tick

NOW = datetime(2026, 11, 1, 13, 30, tzinfo=AMS)
NOW_MS = int(NOW.timestamp() * 1000)


def _blocks(now_price, later_price):
    out = []
    for i in range(24):                      # 6 uur vooruit
        t = NOW + timedelta(minutes=15 * i)
        price = now_price if i == 0 else (0.40 if i < 8 else later_price)
        out.append(Block(key=int(t.timestamp() * 1000), start_iso=t.isoformat(), price=price, dur_h=0.25))
    return out


def _run(soc_kwh, later_price, now_price=0.418, plan=None, afname_w=300):
    """plan: {kwartier-index: actie-dict}"""
    blocks = _blocks(now_price, later_price)
    sched = {blocks[i].key: a for i, a in (plan or {}).items()}
    inp = Inputs(now_ms=NOW_MS, strategy="hybrid", price=now_price, feed_in_discount=0.11,
                 grid_import_w=afname_w, grid_export_w=0.0, cap_kwh=12.0, max_kw=3.5, min_soc_pct=0,
                 ha_soc=soc_kwh, base_load_fallback_w=800, blocks=blocks, schedule=sched)
    return engine_tick(inp, State())


O = {"action": "ontladen", "power_w": 3500}
L = {"action": "laden", "power_w": 3500}


def test_voorraad_gereserveerd_voor_geplande_ontlading():
    # 0,6 kWh, plan ontlaadt later 0,875 kWh: alles is gereserveerd
    assert _run(0.6, 0.514, plan={14: O})["power_w"] == 0


def test_gereserveerd_met_laden_ertussen():
    # 13:45 wordt bijgeladen (+0,81 kWh), daarna twee volle ontlaadkwartieren (2 x 0,95 kWh nodig): niets vrij
    assert _run(0.807, 0.514, plan={1: L, 14: O, 18: O})["power_w"] == 0


def test_vrije_voorraad_wordt_gebruikt_als_later_niet_beter():
    # 3 kWh, plan heeft maar 0,95 kWh nodig; latere prijzen zijn lager dan nu
    assert _run(3.0, 0.35, plan={14: O})["power_w"] < 0


def test_vrije_voorraad_wacht_op_duurder_later():
    # 0,6 kWh vrij (geen plan), later zelfverbruik tegen 0,514: nu niet ontladen
    assert _run(0.6, 0.514)["power_w"] == 0


def test_ontlaadt_nu_als_later_goedkoper_zonder_plan():
    assert _run(0.6, 0.35)["power_w"] < 0


def test_ontlaadt_nu_als_voorraad_alle_latere_toepassingen_dekt():
    # 11,5 kWh is veel meer dan het verbruik tot het einde van de horizon: geen betere latere toepassing
    assert _run(11.5, 0.514)["power_w"] < 0
