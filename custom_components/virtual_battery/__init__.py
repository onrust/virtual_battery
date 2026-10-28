"""Virtual Battery: a virtual home battery simulation for Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
import voluptuous as vol

from .const import DOMAIN, PLATFORMS
from .coordinator import VirtualBatteryCoordinator


SERVICE_SET_STATE = "set_state"
SERVICE_IMPORT_HISTORY = "import_history"
SERVICE_GENERATE_DASHBOARD = "generate_dashboard"
SET_STATE_SCHEMA = vol.Schema({
    vol.Optional("soc"): vol.Coerce(float),
    vol.Optional("average_cost"): vol.Coerce(float),
    vol.Optional("revenue_total"): vol.Coerce(float),
    vol.Optional("revenue_today"): vol.Coerce(float),
    vol.Optional("entry_id"): str,
})


def _apply_state(coord, soc=None, average_cost=None, revenue_total=None, revenue_today=None) -> None:
    """Zet de beginstand (eenmalig, bijv. kopiëren van een bestaande batterij)."""
    st = coord.engine_state
    if soc is not None:
        st.soc = min(max(float(soc), 0.0), coord.settings["capacity"])
    if average_cost is not None:
        st.avgcost = float(average_cost)
    if revenue_total is not None:
        st.total = float(revenue_total)
    if revenue_today is not None:
        st.today = float(revenue_today)
    coord._request_save(2, urgent=True)
    coord._schedule_replan()


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_STATE):
        return

    async def _set_state(call: ServiceCall) -> None:
        data = dict(call.data)
        entry_id = data.pop("entry_id", None)
        for eid, coord in hass.data.get(DOMAIN, {}).items():
            if entry_id in (None, eid):
                _apply_state(coord, **data)

    hass.services.async_register(DOMAIN, SERVICE_SET_STATE, _set_state, schema=SET_STATE_SCHEMA)

    async def _import_history(call: ServiceCall) -> None:
        for coord in hass.data.get(DOMAIN, {}).values():
            await coord.async_import_history(call.data.get("days", 10))

    hass.services.async_register(DOMAIN, SERVICE_IMPORT_HISTORY, _import_history,
                                 schema=vol.Schema({vol.Optional("days", default=10): vol.Coerce(int)}))

    async def _generate_dashboard(call: ServiceCall) -> dict:
        """Bouw het dashboard met de eigen entiteiten, schrijf het naar /config/virtual_battery/ en geef het (alleen de views) terug."""
        from homeassistant.util.yaml import dump
        from .dashboard import build_dashboard

        out: dict = {}
        for coord in hass.data.get(DOMAIN, {}).values():
            cfg = build_dashboard(coord.cfg)
            path = hass.config.path("virtual_battery", "dashboard.yaml")

            def _write(text: str = dump(cfg), p: str = path) -> None:
                import os
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(text)

            await hass.async_add_executor_job(_write)
            out = cfg
            break
        return out

    hass.services.async_register(DOMAIN, SERVICE_GENERATE_DASHBOARD, _generate_dashboard, schema=vol.Schema({}),
                                 supports_response=SupportsResponse.OPTIONAL)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = VirtualBatteryCoordinator(hass, entry)
    await coordinator.async_setup()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _register_services(hass)
    coordinator.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        coordinator: VirtualBatteryCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SET_STATE)
            hass.services.async_remove(DOMAIN, SERVICE_IMPORT_HISTORY)
            hass.services.async_remove(DOMAIN, SERVICE_GENERATE_DASHBOARD)
    return ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
