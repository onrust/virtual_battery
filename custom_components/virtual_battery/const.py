"""Constants for Virtual Battery."""
from __future__ import annotations

DOMAIN = "virtual_battery"
PLATFORMS = ["sensor", "number", "select", "date", "time"]

# --- configuratie (config flow) ---
CONF_NAME = "name"
CONF_NORDPOOL = "nordpool_sensor"
CONF_PRICE = "price_sensor"                    # optioneel: actuele (all-in) prijs, anders Nordpool-stand
CONF_GRID_IMPORT = "grid_import_power"         # W of kW, afname
CONF_GRID_EXPORT = "grid_export_power"         # W of kW, teruglevering
CONF_SOLAR_POWER = "solar_power"
CONF_SOLAR_ENERGY = "solar_energy"             # kWh teller (statistiek)
CONF_IMPORT_ENERGY = "grid_import_energy"      # kWh teller
CONF_EXPORT_ENERGY = "grid_export_energy"      # kWh teller
CONF_EV_POWER = "ev_power"                     # optioneel
CONF_EV_ENERGY = "ev_energy"                   # optioneel
CONF_FORECAST_TODAY = "forecast_today"
CONF_FORECAST_TOMORROW = "forecast_tomorrow"
CONF_FORECAST_REMAINING = "forecast_remaining"  # optioneel
CONF_CAPACITY = "capacity_kwh"
CONF_MAX_POWER = "max_power_kw"
CONF_DEPRECIATION = "depreciation_cent"
CONF_FEED_IN = "feed_in_discount"

DEFAULT_NAME = "Virtual battery"

# --- instellingen die als entiteiten beschikbaar zijn ---
STRATEGIES = ["price_optimization", "zero_meter", "hybrid", "charge_now", "discharge_now", "off"]
EV_POLICIES = ["never", "night_only", "always"]
DEFAULT_STRATEGY = "hybrid"
DEFAULT_EV_POLICY = "never"

# Oudere (Nederlandstalige) opslagwaarden -> sleutels
LEGACY_OPTIONS = {
    "Prijsoptimalisatie": "price_optimization",
    "Nul op de meter": "zero_meter",
    "Hybride (prijs + zelfverbruik)": "hybrid",
    "Nu opladen": "charge_now",
    "Nu ontladen": "discharge_now",
    "Uit": "off",
    "Nooit": "never",
    "Alleen 's avonds/'s nachts": "night_only",
    "Altijd toegestaan (indien voordelig)": "always",
}

# key: (min, max, step, unit, default, mode)
NUMBER_SETTINGS = {
    "capacity": (1.0, 100.0, 0.5, "kWh", 8.0, "slider"),
    "max_power": (0.5, 50.0, 0.5, "kW", 2.5, "slider"),
    "min_soc": (0.0, 50.0, 1.0, "%", 0.0, "slider"),
    "depreciation": (0.0, 100.0, 1.0, "cent", 8.0, "slider"),
    "feed_in_discount": (0.0, 1.0, 0.001, "€/kWh", 0.11, "box"),
    "max_margin": (0.0, 1.0, 0.001, "€/kWh", 0.15, "box"),
    "min_margin": (0.0, 0.3, 0.005, "€/kWh", 0.03, "box"),
    "solar_certainty": (0.0, 100.0, 5.0, "%", 80.0, "slider"),
    "profile_weeks": (2.0, 6.0, 1.0, None, 4.0, "slider"),
    "profile_weight_last": (0.0, 100.0, 1.0, "%", 20.0, "slider"),
    "profile_mix": (0.0, 100.0, 5.0, "%", 10.0, "slider"),
}
# instellingen die de planning direct beïnvloeden -> herberekenen (3 s vertraging)
REPLAN_KEYS = {"capacity", "min_soc", "max_power", "depreciation", "strategy", "solar_certainty", "feed_in_discount", "max_margin", "min_margin", "ev_policy"}
PROFILE_KEYS = {"profile_weeks", "profile_weight_last", "profile_mix"}

TICK_SECONDS = 2
REPLAN_DELAY_SECONDS = 3
