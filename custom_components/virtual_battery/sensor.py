"""Sensoren: toestand, vermogens, opbrengst en verwachtingen."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VirtualBatteryCoordinator
from .entity import VirtualBatteryEntity


@dataclass(frozen=True)
class VBSensorDef:
    key: str
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    icon: str | None = None
    precision: int | None = None
    value: Callable[[VirtualBatteryCoordinator], Any] = lambda c: None
    attrs: Callable[[VirtualBatteryCoordinator], dict] | None = None
    unrecorded: bool = False


def _out(key: str) -> Callable[[VirtualBatteryCoordinator], Any]:
    return lambda c: c.outputs.get(key)


def _profile_attrs(c) -> dict:
    """Profiel als dict per dag (JS-volgorde zo..za, zodat dashboards ongewijzigd blijven) + komende uren."""
    out: dict = {}
    if c.profile:
        names = ["zo", "ma", "di", "wo", "do", "vr", "za"]
        # profiel is maandag = 0 -> JS getDay: zo = 0
        out["profiel"] = {n: c.profile[(i - 1) % 7] for i, n in enumerate(names)}
    out["komende_uren"] = c.profile_info.get("upcoming", [])
    out.update({k: v for k, v in c.profile_info.items() if k != "upcoming"})
    return out


SENSORS: tuple[VBSensorDef, ...] = (
    VBSensorDef("soc", "kWh", SensorDeviceClass.ENERGY_STORAGE, SensorStateClass.MEASUREMENT, "mdi:battery", 2, _out("soc_kwh")),
    VBSensorDef("soc_percent", PERCENTAGE, SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT, None, 1, _out("soc_pct")),
    VBSensorDef("power", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:battery-charging", 0, _out("power_w")),
    VBSensorDef("charge_power", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, None, 0, _out("charge_w")),
    VBSensorDef("discharge_power", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, None, 0, _out("discharge_w")),
    VBSensorDef("combined_power", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, None, 0, _out("combined_w")),
    VBSensorDef("house_consumption", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:home-lightning-bolt", 0, _out("house_w")),
    VBSensorDef("effective_import", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, None, 0, _out("effective_import_w")),
    VBSensorDef("effective_export", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, None, 0, _out("effective_export_w")),
    VBSensorDef("revenue_today", "€", None, SensorStateClass.MEASUREMENT, "mdi:cash", 3, _out("revenue_today")),
    VBSensorDef("revenue_total", "€", None, SensorStateClass.MEASUREMENT, "mdi:cash-multiple", 3, _out("revenue_total")),
    VBSensorDef("average_cost", "€/kWh", None, SensorStateClass.MEASUREMENT, None, 3, _out("avg_cost")),
    VBSensorDef("settlement_price", "€/kWh", None, SensorStateClass.MEASUREMENT, None, 3, _out("settle_price")),
    VBSensorDef("reason", None, None, None, "mdi:comment-text", None, lambda c: (c.outputs.get("reason") or "")[:255]),
    VBSensorDef("schedule_code", None, None, None, "mdi:calendar-clock", None,
                lambda c: (c.outputs.get("schema_code") or "")[:255], unrecorded=True),
    VBSensorDef("expected_revenue", "€", None, None, "mdi:cash-clock", 3, lambda c: c.sim.get("state"),
                lambda c: {k: v for k, v in c.sim.items() if k != "state"}, True),
    VBSensorDef("solar_forecast", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, None, "mdi:weather-sunny", 2,
                lambda c: c.solar_sensor.get("state"), lambda c: c.solar_sensor.get("attributes", {}), True),
    VBSensorDef("expected_consumption", UnitOfPower.WATT, SensorDeviceClass.POWER, None, "mdi:home-lightning-bolt-outline", 0,
                lambda c: c.profile_info.get("upcoming", [[0, None]])[0][1] if c.profile_info.get("upcoming") else None,
                _profile_attrs, True),
    VBSensorDef("day_view", "€", None, None, "mdi:calendar-today", 3, lambda c: c.day_view_data()["totalen"]["opbrengst"],
                lambda c: c.day_view_data(), True),
    VBSensorDef("moment_view", UnitOfPower.WATT, SensorDeviceClass.POWER, None, "mdi:clock-time-four-outline", 0,
                lambda c: c.moment_data().get("vermogen_w"), lambda c: c.moment_data(), True),
    VBSensorDef("plan", None, None, None, "mdi:chart-timeline-variant", None, lambda c: c.plan_info.get("plan"),
                lambda c: dict(c.plan_info), True),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: VirtualBatteryCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(VirtualBatterySensor(coordinator, d) for d in SENSORS)


class VirtualBatterySensor(VirtualBatteryEntity, SensorEntity):
    _unrecorded_attributes = frozenset({"reeks", "soc_reeks", "ontlaad_split", "laad_split", "wh_period", "wh_period_raw", "profiel", "komende_uren", "reeks_dag", "kolommen", "totalen", "datum", "tijd", "gevonden", "kwartier_start", "prijs", "plan_actie", "soort", "soc", "soc_plan", "reden", "huis_kwh", "auto_kwh", "huis_excl_auto_kwh", "zon_kwh", "geladen_kwh", "ontladen_kwh", "afname_kwh", "terug_kwh", "opbrengst", "vermogen_w"})

    def __init__(self, coordinator: VirtualBatteryCoordinator, d: VBSensorDef) -> None:
        super().__init__(coordinator, d.key)
        self._def = d
        self._attr_native_unit_of_measurement = d.unit
        self._attr_device_class = d.device_class
        self._attr_state_class = d.state_class
        self._attr_icon = d.icon
        if d.precision is not None:
            self._attr_suggested_display_precision = d.precision

    @property
    def native_value(self) -> Any:
        return self._def.value(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict | None:
        return self._def.attrs(self.coordinator) if self._def.attrs else None
