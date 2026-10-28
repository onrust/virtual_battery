"""Config flow en options flow."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CAPACITY, CONF_DEPRECIATION, CONF_EV_ENERGY, CONF_EV_POWER, CONF_EXPORT_ENERGY,
    CONF_FEED_IN, CONF_FORECAST_REMAINING, CONF_FORECAST_TODAY, CONF_FORECAST_TOMORROW,
    CONF_GRID_EXPORT, CONF_GRID_IMPORT, CONF_IMPORT_ENERGY, CONF_MAX_POWER, CONF_NAME,
    CONF_NORDPOOL, CONF_PRICE, CONF_SOLAR_ENERGY, CONF_SOLAR_POWER, DEFAULT_NAME, DOMAIN,
)


def _sensor(**kw) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", **kw))


def _num(min_, max_, step, unit) -> selector.NumberSelector:
    return selector.NumberSelector(selector.NumberSelectorConfig(
        min=min_, max=max_, step=step, unit_of_measurement=unit, mode=selector.NumberSelectorMode.BOX))


def sensors_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_NORDPOOL): _sensor(),
        vol.Optional(CONF_PRICE): _sensor(),
        vol.Required(CONF_GRID_IMPORT): _sensor(),
        vol.Required(CONF_GRID_EXPORT): _sensor(),
        vol.Required(CONF_SOLAR_POWER): _sensor(),
        vol.Required(CONF_SOLAR_ENERGY): _sensor(),
        vol.Required(CONF_IMPORT_ENERGY): _sensor(),
        vol.Required(CONF_EXPORT_ENERGY): _sensor(),
        vol.Optional(CONF_EV_POWER): _sensor(),
        vol.Optional(CONF_EV_ENERGY): _sensor(),
        vol.Required(CONF_FORECAST_TODAY): _sensor(),
        vol.Required(CONF_FORECAST_TOMORROW): _sensor(),
        vol.Optional(CONF_FORECAST_REMAINING): _sensor(),
    })


def battery_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_CAPACITY, default=8.0): _num(1, 100, 0.5, "kWh"),
        vol.Required(CONF_MAX_POWER, default=2.5): _num(0.5, 50, 0.5, "kW"),
        vol.Required(CONF_DEPRECIATION, default=8): _num(0, 100, 1, "cent"),
        vol.Required(CONF_FEED_IN, default=0.11): _num(0, 1, 0.001, "€/kWh"),
    })


class VirtualBatteryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_battery()
        return self.async_show_form(step_id="user", data_schema=sensors_schema())

    async def async_step_battery(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
        return self.async_show_form(step_id="battery", data_schema=battery_schema())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return VirtualBatteryOptionsFlow()


class VirtualBatteryOptionsFlow(config_entries.OptionsFlow):
    """Sensoren aanpassen (de batterij-instellingen zelf zijn entiteiten)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        schema = sensors_schema()
        return self.async_show_form(step_id="init", data_schema=self.add_suggested_values_to_schema(schema, current))
