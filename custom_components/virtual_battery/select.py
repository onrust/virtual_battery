"""Strategie en EV-beleid als select-entiteiten."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EV_POLICIES, STRATEGIES
from .coordinator import VirtualBatteryCoordinator
from .entity import VirtualBatteryEntity

OPTIONS = {"strategy": STRATEGIES, "ev_policy": EV_POLICIES}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: VirtualBatteryCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(VirtualBatterySelect(coordinator, k) for k in OPTIONS)


class VirtualBatterySelect(VirtualBatteryEntity, SelectEntity):
    _platform_domain = "select"
    def __init__(self, coordinator: VirtualBatteryCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._attr_options = list(OPTIONS[key])

    @property
    def current_option(self) -> str:
        return self.coordinator.settings[self._key]

    async def async_select_option(self, option: str) -> None:
        self.coordinator.async_set_setting(self._key, option)
