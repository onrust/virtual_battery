"""Instellingen als number-entiteiten."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NUMBER_SETTINGS
from .coordinator import VirtualBatteryCoordinator
from .entity import VirtualBatteryEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: VirtualBatteryCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(VirtualBatteryNumber(coordinator, k) for k in NUMBER_SETTINGS)


class VirtualBatteryNumber(VirtualBatteryEntity, NumberEntity):
    _platform_domain = "number"
    def __init__(self, coordinator: VirtualBatteryCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        lo, hi, step, unit, _default, mode = NUMBER_SETTINGS[key]
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_mode = NumberMode.SLIDER if mode == "slider" else NumberMode.BOX

    @property
    def native_value(self) -> float:
        return self.coordinator.settings[self._key]

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.async_set_setting(self._key, float(value))
