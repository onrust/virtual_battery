"""Gedeelde basisklasse."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.util import slugify

from .const import CONF_NAME, DOMAIN
from .coordinator import VirtualBatteryCoordinator


class VirtualBatteryEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _platform_domain = "sensor"

    def __init__(self, coordinator: VirtualBatteryCoordinator, key: str) -> None:
        self.coordinator = coordinator
        self._key = key
        self._attr_translation_key = key
        # taalonafhankelijke entity_id: <domein>.<naam>_<sleutel> (dashboards blijven dan werken)
        self.entity_id = f"{self._platform_domain}.{slugify(coordinator.cfg.get(CONF_NAME, 'virtual_battery'))}_{key}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.cfg.get(CONF_NAME, "Virtual battery"),
            manufacturer="Virtual Battery",
            model="Simulatie",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
