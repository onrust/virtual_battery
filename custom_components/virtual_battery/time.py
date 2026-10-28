"""Tijdkeuze (kwartier) voor het dagarchief."""
from __future__ import annotations

from datetime import time as dtime

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VirtualBatteryCoordinator
from .entity import VirtualBatteryEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([VirtualBatteryViewTime(hass.data[DOMAIN][entry.entry_id], "view_time")])


class VirtualBatteryViewTime(VirtualBatteryEntity, TimeEntity):
    _platform_domain = "time"
    _attr_icon = "mdi:clock-search"

    @property
    def native_value(self) -> dtime:
        h, m = (int(x) for x in self.coordinator.view_hhmm().split(":")[:2])
        return dtime(h, m)

    async def async_set_value(self, value: dtime) -> None:
        self.coordinator.async_set_view_time(f"{value.hour:02d}:{value.minute:02d}")
