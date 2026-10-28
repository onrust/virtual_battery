"""Tests voor config flow en het opstarten van de integratie."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.virtual_battery.const import DOMAIN

AMS = ZoneInfo("Europe/Amsterdam")

SENSORS = {
    "name": "VB test",
    "nordpool_sensor": "sensor.nordpool",
    "grid_import_power": "sensor.net_afname",
    "grid_export_power": "sensor.net_teruglevering",
    "solar_power": "sensor.zon_vermogen",
    "solar_energy": "sensor.zon_energie",
    "grid_import_energy": "sensor.net_import_kwh",
    "grid_export_energy": "sensor.net_export_kwh",
    "ev_power": "sensor.laadpaal_vermogen",
    "forecast_today": "sensor.forecast_vandaag",
    "forecast_tomorrow": "sensor.forecast_morgen",
}
BATTERY = {"capacity_kwh": 8.0, "max_power_kw": 2.5, "depreciation_cent": 8, "feed_in_discount": 0.11}


def _price_attrs():
    day0 = datetime.now(AMS).replace(hour=0, minute=0, second=0, microsecond=0)
    def day(d0, base):
        return [{"start": d0 + timedelta(minutes=15 * i), "end": d0 + timedelta(minutes=15 * (i + 1)),
                 "value": round(base + 0.1 * (1 if 17 <= (i // 4) <= 20 else 0) - 0.05 * (1 if 2 <= (i // 4) <= 5 else 0), 3)} for i in range(96)]
    return {"raw_today": day(day0, 0.3), "raw_tomorrow": day(day0 + timedelta(days=1), 0.32), "tomorrow_valid": True}


def _forecast_attrs(offset_days):
    day0 = datetime.now(AMS).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=offset_days)
    wh = {}
    for i in range(96):
        h = i / 4
        wh[(day0 + timedelta(minutes=15 * i)).isoformat()] = max(0, 1200 * (1 - ((h - 12.5) / 5) ** 2)) if 7 <= h <= 18 else 0
    return {"wh_period_15m": wh}


def _set_states(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.nordpool", "0.30", _price_attrs())
    hass.states.async_set("sensor.net_afname", "1200", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.net_teruglevering", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.zon_vermogen", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.laadpaal_vermogen", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.forecast_vandaag", "10", _forecast_attrs(0))
    hass.states.async_set("sensor.forecast_morgen", "10", _forecast_attrs(1))


async def test_config_flow(hass: HomeAssistant) -> None:
    _set_states(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], SENSORS)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "battery"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], BATTERY)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["nordpool_sensor"] == "sensor.nordpool"
    assert result["data"]["capacity_kwh"] == 8.0
    # tweede instantie wordt geweigerd
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert again["type"] is FlowResultType.ABORT


async def test_setup_and_run(hass: HomeAssistant) -> None:
    _set_states(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={**SENSORS, **BATTERY}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # entiteiten bestaan
    names = {s.entity_id for s in hass.states.async_all() if s.entity_id.startswith(("sensor.vb_test", "number.vb_test", "select.vb_test"))}
    assert "select.vb_test_strategy" in names or any(n.endswith("strategie") for n in names), names
    assert len(names) >= 25, names

    # een tick laten draaien
    async_fire_time_changed(hass, datetime.now(timezone.utc) + timedelta(seconds=3))
    await hass.async_block_till_done(wait_background_tasks=True)
    soc = hass.states.get("sensor.vb_test_soc")
    assert soc is not None and soc.state not in ("unknown", "unavailable"), soc

    # instelling wijzigen -> opgeslagen in de coördinator
    coord = hass.data[DOMAIN][entry.entry_id]
    await hass.services.async_call("number", "set_value", {"entity_id": "number.vb_test_capacity", "value": 12}, blocking=True)
    assert coord.settings["capacity"] == 12.0
    await hass.services.async_call("select", "select_option", {"entity_id": "select.vb_test_strategy", "option": "charge_now"}, blocking=True)
    assert coord.settings["strategy"] == "charge_now"

    # planning draait
    await coord.async_replan()
    assert len(coord.schedule) == 192
    assert coord.sim.get("state") is not None

    # "Nu opladen" -> laden met vol vermogen
    async_fire_time_changed(hass, datetime.now(timezone.utc) + timedelta(seconds=8))
    await hass.async_block_till_done(wait_background_tasks=True)
    p = hass.states.get("sensor.vb_test_power")
    assert p is not None and float(p.state) > 0, p

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_custom_name(hass: HomeAssistant) -> None:
    """Een andere instantienaam geeft gewoon <naam>_<sleutel> entiteiten, zonder 'vb_test'."""
    _set_states(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={**SENSORS, **BATTERY, "name": "Mijn Thuisbatterij"}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, datetime.now(timezone.utc) + timedelta(seconds=3))
    await hass.async_block_till_done(wait_background_tasks=True)
    for eid in ("sensor.mijn_thuisbatterij_soc", "number.mijn_thuisbatterij_capacity", "select.mijn_thuisbatterij_strategy"):
        assert hass.states.get(eid) is not None, eid
    assert not [s for s in hass.states.async_all() if "vb_test" in s.entity_id]


async def test_legacy_options_migrate(hass: HomeAssistant, hass_storage) -> None:
    """Oude (Nederlandse) opslagwaarden van strategie/EV-beleid worden naar sleutels omgezet."""
    _set_states(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={**SENSORS, **BATTERY}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {"version": 1, "minor_version": 1, "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"settings": {"strategy": "Nul op de meter", "ev_policy": "Alleen 's avonds/'s nachts"}}}
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = hass.data[DOMAIN][entry.entry_id]
    assert coord.settings["strategy"] == "zero_meter"
    assert coord.settings["ev_policy"] == "night_only"
