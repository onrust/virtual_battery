"""Tests voor het dagarchief (kwartierrijen, historie, dagoverzicht) en de datum-/tijdkeuze."""
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_battery.const import DOMAIN
from custom_components.virtual_battery.logic import archive as arch
from tests.test_integration import BATTERY, SENSORS, _set_states

AMS = ZoneInfo("Europe/Amsterdam")


def _ms(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=AMS).timestamp() * 1000)


def test_accumulator_integrates_energy_and_classifies():
    key = _ms(2026, 10, 27, 12)
    a = arch.QuarterAcc(key, 0.30, "L", 3.0)
    out = {"charge_w": 2000.0, "discharge_w": 0.0, "house_w": 500.0, "effective_import_w": 0.0,
           "effective_export_w": 0.0, "soc_kwh": 4.0, "revenue_total": 10.0, "reason": "Laden"}
    for i in range(450):                                   # 450 ticks van 2 s = 15 min
        out["revenue_total"] = 10.0 + i * 0.0001
        a.add(2.0 if i else 0.0, out, 3000.0)
    row = a.to_row()
    g = {c: row[arch.IDX[c]] for c in arch.COLS}
    assert abs(g["charge"] - 0.5) < 0.01                   # 2 kW * 0,25 h
    assert abs(g["house"] - 0.125) < 0.01
    assert abs(g["charge_solar"] - g["charge"]) < 0.01     # zon 3000 - huis 500 >= laden 2000
    assert g["kind"] == "Z" and g["plan"] == "L" and g["soc_plan"] == 3.0 and g["rev"] > 0


def test_accumulator_ignores_large_gaps_and_classify_discharge():
    a = arch.QuarterAcc(0, 0.3, "O", None)
    a.add(3600.0, {"discharge_w": 5000.0}, None)           # herstart-gat telt niet mee
    assert a.discharge == 0
    assert arch.classify(0, 1.0, 0, 0.9) == "E" and arch.classify(0, 1.0, 0, 0.1) == "H"
    assert arch.classify(1.0, 0, 0.1, 0) == "N" and arch.classify(0, 0, 0, 0) == "I"


def test_rows_from_history_and_day_view():
    t0 = _ms(2026, 10, 20, 0)
    t1 = t0 + 6 * arch.QUARTER_MS
    num = {"charge_w": [(t0, 0.0), (t0 + arch.QUARTER_MS, 2000.0), (t0 + 2 * arch.QUARTER_MS, 0.0)],
           "discharge_w": [(t0, 0.0)], "soc": [(t0, 1.0), (t0 + 2 * arch.QUARTER_MS, 1.5)],
           "price": [(t0, 0.2)], "solar_w": [(t0, 0.0)], "house_w": [(t0, 400.0)],
           "rev_total": [(t0, 5.0), (t0 + 2 * arch.QUARTER_MS, 5.5)]}
    rows = arch.rows_from_history(num, {"reason": [(t0, "Laden @ 2000 W")]}, t0, t1)
    assert len(rows) == 6
    q1 = rows[1]
    assert abs(q1[arch.IDX["charge"]] - 0.5) < 1e-6 and q1[arch.IDX["kind"]] == "N"
    assert rows[0][arch.IDX["kind"]] == "I"
    v = arch.day_view(rows, "2026-10-20")
    assert v["totalen"]["kwartieren"] == 6 and abs(v["totalen"]["geladen_kwh"] - 0.5) < 1e-6
    assert abs(v["totalen"]["opbrengst"] - 0.5) < 1e-6 and len(v["reeks"]) == 6
    assert arch.day_view(rows, "2026-10-21")["totalen"]["kwartieren"] == 0
    assert arch.moment_row(rows, "2026-10-20", "00:20")[0] == t0 + arch.QUARTER_MS
    assert arch.moment_row(rows, "2026-10-20", "09:00") is None


def test_rows_skip_quarters_without_data():
    assert arch.rows_from_history({"charge_w": [], "soc": []}, {}, 0, 3 * arch.QUARTER_MS) == []


async def _setup(hass: HomeAssistant):
    _set_states(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={**SENSORS, **BATTERY}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]


async def test_date_time_entities_and_views(hass: HomeAssistant) -> None:
    entry, coord = await _setup(hass)
    gisteren = (datetime.now(AMS) - timedelta(days=1)).date()
    t = _ms(gisteren.year, gisteren.month, gisteren.day, 18, 15)
    rij = [t, 0.30, 0.0, 0.5, 0.2, 0.0, 0.0, 0.0, 0.07, 3.0, "O", "H", 3.1, "Ontladen @ 2000 W", 0.0, 0.0]
    await coord.archive.async_add_rows([rij])

    await hass.services.async_call("date", "set_value", {"entity_id": "date.vb_test_view_date", "date": gisteren.isoformat()}, blocking=True)
    await hass.services.async_call("time", "set_value", {"entity_id": "time.vb_test_view_time", "time": "18:20:00"}, blocking=True)
    await hass.async_block_till_done()

    assert hass.states.get("date.vb_test_view_date").state == gisteren.isoformat()
    assert hass.states.get("time.vb_test_view_time").state == "18:20:00"
    dag = hass.states.get("sensor.vb_test_day_view")
    assert dag.state == "0.07" and dag.attributes["totalen"]["ontladen_kwh"] == 0.5
    assert dag.attributes["reeks"][0][0] == t
    mom = hass.states.get("sensor.vb_test_moment_view")
    assert mom.state == "-2000" and mom.attributes["reden"].startswith("Ontladen")
    assert mom.attributes["kwartier_start"] == "18:15" and mom.attributes["soort"] == "H"

    # vandaag kiezen = vandaag volgen
    await hass.services.async_call("date", "set_value", {"entity_id": "date.vb_test_view_date", "date": datetime.now(AMS).date().isoformat()}, blocking=True)
    assert coord.view_date is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_archive_survives_restart_and_purges(hass: HomeAssistant, hass_storage) -> None:
    entry, coord = await _setup(hass)
    oud = [_ms(2020, 1, 5, 12), 0.2, 0, 0, 0, 0, 0, 0, 0, 1.0, None, "I", None, "", 0, 0]
    nu = [int(datetime.now(AMS).replace(minute=0, second=0, microsecond=0).timestamp() * 1000) - 3600000] + oud[1:]
    await coord.archive.async_add_rows([oud, nu])
    await coord.archive.async_save()
    await coord.archive.async_purge()
    assert not coord.archive.has_row(oud[0]) and coord.archive.has_row(nu[0])
    await hass.config_entries.async_unload(entry.entry_id)
    keys = [k for k in hass_storage if ".archive." in k]
    assert keys and all("2020-01" not in k for k in keys if hass_storage[k].get("data", {}).get("rows"))


async def test_live_archiving_finalizes_each_quarter(hass: HomeAssistant) -> None:
    from custom_components.virtual_battery.logic.engine import Inputs
    entry, coord = await _setup(hass)
    base = arch.quarter_start(int(datetime.now(AMS).timestamp() * 1000)) - 2 * arch.QUARTER_MS
    coord.acc, coord._last_arch_ms = None, 0
    coord.outputs = {"charge_w": 1000.0, "discharge_w": 0.0, "house_w": 300.0, "effective_import_w": 0.0,
                     "effective_export_w": 0.0, "soc_kwh": 2.0, "revenue_total": 1.0, "reason": "Laden"}
    inp = Inputs.__new__(Inputs)
    inp.price, inp.solar_w = 0.25, 0.0
    for ms in range(base, base + 2 * arch.QUARTER_MS + 4000, 2000):
        await coord._archive_tick(ms, inp)
    rijen = coord.archive.rows_for_day(arch.day_of(base))
    t = [r[0] for r in rijen if r[0] in (base, base + arch.QUARTER_MS)]
    assert t == [base, base + arch.QUARTER_MS]
    r = next(r for r in rijen if r[0] == base)
    assert abs(r[arch.IDX["charge"]] - 0.25) < 0.01 and r[arch.IDX["kind"]] == "N"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_import_history_fills_archive(hass: HomeAssistant, monkeypatch) -> None:
    from types import SimpleNamespace
    entry, coord = await _setup(hass)
    now = arch.quarter_start(int(datetime.now(AMS).timestamp() * 1000))
    t0 = now - 4 * arch.QUARTER_MS

    def st(v, ms):
        return SimpleNamespace(state=str(v), last_updated=datetime.fromtimestamp(ms / 1000, AMS))

    def fake(hass_, start, end, ids, **kw):
        res = {}
        for eid in ids:
            if eid.endswith("_charge_power"):
                res[eid] = [st(0, t0), st(1500, t0 + arch.QUARTER_MS), st(0, t0 + 2 * arch.QUARTER_MS)]
            elif eid.endswith("_soc"):
                res[eid] = [st(1.0, t0), st(1.4, t0 + 2 * arch.QUARTER_MS)]
            elif eid.endswith("_discharge_power"):
                res[eid] = [st(0, t0)]
        return res

    monkeypatch.setattr("homeassistant.components.recorder.history.get_significant_states", fake)
    coord._imported = False
    n = await coord.async_import_history(1)
    assert n >= 3 and coord._imported
    rij = coord.archive.rows_for_day(arch.day_of(t0 + arch.QUARTER_MS))
    q = next(r for r in rij if r[0] == t0 + arch.QUARTER_MS)
    assert abs(q[arch.IDX["charge"]] - 0.375) < 1e-6
    await hass.config_entries.async_unload(entry.entry_id)


def test_invalid_solar_values_are_ignored():
    a = arch.QuarterAcc(0, 0.3, None, None)
    a.add(2.0, {"house_w": 100.0}, -536870.912)
    a.add(2.0, {"house_w": 100.0}, 99999.0)
    assert a.solar == 0.0
    t0 = 0
    num = {"charge_w": [(0, 0.0)], "soc": [(0, 1.0)], "solar_w": [(0, -536870.912), (450000, 800.0)]}
    r = arch.rows_from_history(num, {}, t0, arch.QUARTER_MS)[0]
    assert 0 <= r[arch.IDX["solar"]] < 0.2
    bad = list(r)
    bad[arch.IDX["solar"]] = -134217.0
    assert arch.solar_invalid(bad) and not arch.solar_invalid(r)


def test_ev_column_in_rows_and_views():
    a = arch.QuarterAcc(_ms(2026, 10, 27, 0), 0.2, None, None)
    for i in range(450):
        a.add(2.0 if i else 0.0, {"house_w": 10700.0, "charge_w": 0.0}, 0.0, 10300.0)
    row = a.to_row()
    assert abs(arch.val(row, "ev") - 2.575) < 0.02
    old = row[:-1]                                         # oude rij zonder autokolom
    assert arch.val(old, "ev") is None and arch.needs_repair(old) and not arch.needs_repair(row)
    v = arch.day_view([row, old], "2026-10-27")
    assert v["totalen"]["auto_kwh"] > 2.5 and v["totalen"]["huis_excl_auto_kwh"] is None
    assert v["reeks"][0][-1] == row[arch.IDX["ev"]] and v["reeks"][1][-1] is None
    num = {"charge_w": [(0, 0.0)], "soc": [(0, 1.0)], "ev_w": [(0, 4000.0)], "house_w": [(0, 4400.0)]}
    r = arch.rows_from_history(num, {}, 0, arch.QUARTER_MS)[0]
    assert abs(arch.val(r, "ev") - 1.0) < 1e-6
    assert arch.val(arch.rows_from_history({"charge_w": [(0, 0.0)], "soc": [(0, 1.0)]}, {}, 0, arch.QUARTER_MS)[0], "ev") is None


def test_dashboard_is_built_with_own_entities():
    import json, re
    from custom_components.virtual_battery.dashboard import build_dashboard
    cfg = {"name": "Mijn Batterij", "nordpool_sensor": "sensor.np", "solar_power": "sensor.pv_w", "solar_energy": "sensor.pv_kwh",
           "grid_import_energy": "sensor.imp", "grid_export_energy": "sensor.exp", "forecast_today": "sensor.f1",
           "forecast_tomorrow": "sensor.f2"}
    c = build_dashboard(cfg)
    s = json.dumps(c)
    assert [v["path"] for v in c["views"]] == ["virtuele-batterij", "forecast", "historie"]
    assert "@@" not in s and "@DAY@" not in s and "tesla" not in s and "tibber" not in s and "virtual_battery_" not in s
    assert "sensor.mijn_batterij_day_view" in s and "date.mijn_batterij_view_date" in s and "sensor.np" in s
    assert "vb_not_configured" not in json.dumps(c["views"][0])      # tegels zonder optionele sensor zijn verwijderd


async def test_generate_dashboard_service(hass: HomeAssistant) -> None:
    import os
    entry, coord = await _setup(hass)
    res = await hass.services.async_call(DOMAIN, "generate_dashboard", {}, blocking=True, return_response=True)
    assert [v["path"] for v in res["views"]] == ["virtuele-batterij", "forecast", "historie"]
    f = hass.config.path("virtual_battery", "dashboard.yaml")
    assert os.path.exists(f) and os.path.getsize(f) > 10000
    await hass.config_entries.async_unload(entry.entry_id)
