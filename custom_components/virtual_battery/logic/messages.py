"""Berichtencatalogus (NL/EN) voor de 'reden'-tekst van de engine.

De engine geeft sleutels + parameters; hier wordt de tekst per taal opgebouwd.
De Nederlandse teksten zijn letterlijk gelijk aan die van de Node-RED-flow.
"""
from __future__ import annotations

LANGS = ("nl", "en")

# Namen van de opties per taal (voor in de reden-tekst: "EV-beleid: ...")
EV_LABELS = {
    "nl": {"never": "Nooit", "night_only": "Alleen 's avonds/'s nachts", "always": "Altijd toegestaan (indien voordelig)"},
    "en": {"never": "Never", "night_only": "Evenings/nights only", "always": "Always allowed (if profitable)"},
}

M: dict[str, dict[str, str]] = {
    "nl": {
        "manual_charge": "Laden @ {w} W — handmatig, vol vermogen",
        "manual_charge_full": "Idle — batterij al vol (handmatig laden)",
        "manual_discharge": "Ontladen @ {w} W — handmatig, vol vermogen",
        "manual_discharge_empty": "Idle — batterij al leeg (handmatig ontladen)",
        "off": "Batterij staat uit (handmatig)",
        "no_price_data": "geen prijsdata resterend vandaag",
        "margin_explain": "haalbare verkoopprijs voor verwachte eindvoorraad ({stock} kWh) €{marginal} vs. nu €{now} (marge €{margin}, vereist €{required} bij {soc}% SoC)",
        "override_emergency": "noodklep actief",
        "override_scarcity": "schaarste: nog {solar} kWh zon verwacht vandaag vs. {room} kWh vrije ruimte (factor {factor}, na {hour}:00u) — grijp deze kans",
        "overflow_factor": "; overvloedfactor {factor}",
        "idle_prefer_feed_in": "Idle — zon-overschot beschikbaar, maar liever nu terugleveren ({explain}{extra})",
        "charge_with_reason": "Laden @ {w} W — {why}",
        "idle_surplus_small": "Idle — zon-overschot te klein om te verwerken",
        "discharge_cover_ev": "Ontladen @ {w} W — dekt tekort incl. autoladen (EV-beleid: {ev})",
        "discharge_cover_house": "Ontladen @ {w} W — dekt huishoudelijk tekort (nul op de meter)",
        "idle_empty_cannot_cover": "Idle — batterij leeg, kan tekort niet dekken",
        "idle_ev_no_supply": "Idle — auto laadt, batterij mag daar niet voor leveren (EV-beleid: {ev})",
        "idle_balanced": "Idle — huishouden in balans (nul op de meter)",
        "self_use_now": "Ontladen @ {w} W — zelfverbruik nu (€{price}) {compare}{context}{excl_ev}",
        "self_use_cheaper": "is voordeliger dan de beste latere toepassing (€{net})",
        "self_use_no_alt": "en er is geen betere latere toepassing beschikbaar vóór het volgende laadmoment",
        "excl_ev": " (excl. autoladen)",
        "store_surplus": "Laden @ {w} W — zon-overschot opslaan (bespaart straks €{threshold}/kWh aan inkoop) is voordeliger dan nu terugleveren (€{price}){context}",
        "idle_plan_discharge_ev": "Idle — dagschema wilde ontladen, maar auto laadt en batterij mag daar niet voor leveren (EV-beleid: {ev})",
        "discharge_best_moment": "Ontladen @ {w} W — dit is het beste resterende verkoopmoment vóór het volgende laadmoment{hybrid}{ev_part}",
        "hybrid_expected_use": " (rekening houdend met verwacht zelfverbruik, nu {base} W)",
        "ev_charges_along": " (auto laadt mee, EV-beleid: {ev})",
        "idle_empty": "Idle — batterij leeg",
        "ctx_reserved": " (terwijl gereserveerd wordt voor verwacht toekomstig zelfverbruik of een beter verkoopmoment)",
        "ctx_wait_better_sale": " (terwijl gewacht wordt op een beter verkoopmoment)",
        "ctx_wait_cheaper_charge": " (terwijl gewacht wordt op een goedkoper laadmoment)",
        "idle_reserved": "Idle — dagschema wilde ontladen, maar deze voorraad wordt gereserveerd voor een beter verkoopmoment en/of verwacht zelfverbruik (nu {base} W) — wachten daarop",
        "charge_cheapest": "Laden @ {w} W — dit is het goedkoopste resterende laadmoment vóór het volgende verkoopmoment (€{price}/kWh{solar_part})",
        "solar_part": ", waarvan {pct}% uit zon-overschot",
        "idle_full": "Idle — batterij vol",
        "idle_wait_cheaper": "Idle — dagschema wilde laden, maar er komt nog een goedkoper moment (€{price}) vóór het volgende verkoopmoment — wachten daarop",
        "idle_not_profitable": "Idle — dit kwartier is volgens het dagschema niet rendabel{extra}",
        "extra_self_use_not_better": " (zelfverbruik nu is ook niet beter dan de beste latere toepassing)",
        "extra_reserved_for_plan": " (de voorraad is gereserveerd voor de geplande ontladingen)",
        "extra_prefer_feed_in": " (zon-overschot liever nu terugleveren dan opslaan)",
        "unknown_strategy": "Onbekende strategie: {strategy}",
    },
    "en": {
        "manual_charge": "Charging @ {w} W — manual, full power",
        "manual_charge_full": "Idle — battery already full (manual charge)",
        "manual_discharge": "Discharging @ {w} W — manual, full power",
        "manual_discharge_empty": "Idle — battery already empty (manual discharge)",
        "off": "Battery is off (manual)",
        "no_price_data": "no price data left today",
        "margin_explain": "achievable sale price for expected final stock ({stock} kWh) €{marginal} vs. now €{now} (margin €{margin}, required €{required} at {soc}% SoC)",
        "override_emergency": "emergency valve active",
        "override_scarcity": "scarcity: {solar} kWh of solar still expected today vs. {room} kWh free capacity (factor {factor}, after {hour}:00) — seize this chance",
        "overflow_factor": "; abundance factor {factor}",
        "idle_prefer_feed_in": "Idle — solar surplus available, but better to feed in now ({explain}{extra})",
        "charge_with_reason": "Charging @ {w} W — {why}",
        "idle_surplus_small": "Idle — solar surplus too small to use",
        "discharge_cover_ev": "Discharging @ {w} W — covers shortfall incl. EV charging (EV policy: {ev})",
        "discharge_cover_house": "Discharging @ {w} W — covers household shortfall (zero on the meter)",
        "idle_empty_cannot_cover": "Idle — battery empty, cannot cover the shortfall",
        "idle_ev_no_supply": "Idle — car is charging, battery may not supply it (EV policy: {ev})",
        "idle_balanced": "Idle — household in balance (zero on the meter)",
        "self_use_now": "Discharging @ {w} W — self-consumption now (€{price}) {compare}{context}{excl_ev}",
        "self_use_cheaper": "is better than the best later use (€{net})",
        "self_use_no_alt": "and there is no better later use before the next charging moment",
        "excl_ev": " (excl. car charging)",
        "store_surplus": "Charging @ {w} W — storing solar surplus (saves €{threshold}/kWh on future purchases) is better than feeding in now (€{price}){context}",
        "idle_plan_discharge_ev": "Idle — schedule wanted to discharge, but the car is charging and the battery may not supply it (EV policy: {ev})",
        "discharge_best_moment": "Discharging @ {w} W — this is the best remaining selling moment before the next charging moment{hybrid}{ev_part}",
        "hybrid_expected_use": " (taking expected self-consumption into account, now {base} W)",
        "ev_charges_along": " (car is charging too, EV policy: {ev})",
        "idle_empty": "Idle — battery empty",
        "ctx_reserved": " (while reserving for expected future self-consumption or a better selling moment)",
        "ctx_wait_better_sale": " (while waiting for a better selling moment)",
        "ctx_wait_cheaper_charge": " (while waiting for a cheaper charging moment)",
        "idle_reserved": "Idle — schedule wanted to discharge, but this stock is reserved for a better selling moment and/or expected self-consumption (now {base} W) — waiting for that",
        "charge_cheapest": "Charging @ {w} W — this is the cheapest remaining charging moment before the next selling moment (€{price}/kWh{solar_part})",
        "solar_part": ", of which {pct}% from solar surplus",
        "idle_full": "Idle — battery full",
        "idle_wait_cheaper": "Idle — schedule wanted to charge, but a cheaper moment (€{price}) is coming before the next selling moment — waiting for that",
        "idle_not_profitable": "Idle — this quarter is not profitable according to the schedule{extra}",
        "extra_self_use_not_better": " (self-consumption now is not better than the best later use either)",
        "extra_reserved_for_plan": " (the stored energy is reserved for the planned discharges)",
        "extra_prefer_feed_in": " (solar surplus better fed in now than stored)",
        "unknown_strategy": "Unknown strategy: {strategy}",
    },
}


def msg(lang: str, key: str, **kw) -> str:
    table = M.get(lang) or M["en"]
    return table[key].format(**kw)


def ev_label(lang: str, ev_policy: str) -> str:
    return (EV_LABELS.get(lang) or EV_LABELS["en"]).get(ev_policy, ev_policy)
