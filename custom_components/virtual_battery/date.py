"""Datumkeuze voor het dagarchief."""
from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VirtualBatteryCoordinator
from .entity import VirtualBatteryEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([VirtualBatteryViewDate(hass.data[DOMAIN][entry.entry_id], "view_date")])


class VirtualBatteryViewDate(VirtualBatteryEntity, DateEntity):
    _platform_domain = "date"
    _attr_icon = "mdi:calendar-search"

    @property
    def native_value(self) -> date:
        return date.fromisoformat(self.coordinator.view_day())

    async def async_set_value(self, value: date) -> None:
        await self.coordinator.async_set_view_date(value.isoformat())
