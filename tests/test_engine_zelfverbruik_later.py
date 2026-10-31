"""Zelfverbruik nu mag alleen als het beter is dan de beste latere toepassing (verkoop of zelfverbruik, tegen marktprijs)."""
from datetime import datetime, timedelta

from custom_components.virtual_battery.logic.engine import AMS, Block, Inputs, State, engine_tick

NOW = datetime(2026, 11, 1, 13, 30, tzinfo=AMS)
NOW_MS = int(NOW.timestamp() * 1000)


def _run(soc_kwh, later_price, now_price=0.418, plan_later=True, afname_w=300):
    blocks = []
    for i in range(24):                      # 6 uur vooruit
        t = NOW + timedelta(minutes=15 * i)
        price = now_price if i == 0 else (0.40 if i < 8 else later_price)
        blocks.append(Block(key=int(t.timestamp() * 1000), start_iso=t.isoformat(), price=price, dur_h=0.25))
    sched = {}
    if plan_later:
        sched[blocks[14].key] = {"action": "ontladen", "power_w": 3500}
    inp = Inputs(now_ms=NOW_MS, strategy="hybrid", price=now_price, feed_in_discount=0.11,
                 grid_import_w=afname_w, grid_export_w=0.0, cap_kwh=12.0, max_kw=3.5, min_soc_pct=0,
                 ha_soc=soc_kwh, base_load_fallback_w=800, blocks=blocks, schedule=sched)
    return engine_tick(inp, State())


def test_bewaart_voorraad_voor_duurder_zelfverbruik_later():
    # nu 0,418; later 0,514 (verkoop netto 0,404, maar zelfverbruik 0,514): niet nu ontladen
    assert _run(0.6, 0.514)["power_w"] == 0


def test_ontlaadt_nu_als_later_goedkoper():
    assert _run(0.6, 0.35)["power_w"] < 0


def test_ontlaadt_nu_als_voorraad_alle_latere_toepassingen_dekt():
    # 11,5 kWh is veel meer dan het verbruik tot het einde van de horizon: geen betere latere toepassing
    assert _run(11.5, 0.514)["power_w"] < 0


def test_zonder_plan_wordt_zelfverbruik_later_toch_gewaardeerd():
    # ook zonder geplande ontlading: de duurste latere kwartieren (huisverbruik) gaan voor
    assert _run(0.6, 0.514, plan_later=False)["power_w"] == 0
