"""Kant-en-klaar dashboard: bouwt de lovelace-configuratie met de entiteiten van deze installatie."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from homeassistant.util import slugify

from ..const import (
    CONF_EV_ENERGY, CONF_EV_POWER, CONF_EXPORT_ENERGY, CONF_FORECAST_TODAY, CONF_FORECAST_TOMORROW,
    CONF_IMPORT_ENERGY, CONF_NAME, CONF_NORDPOOL, CONF_SOLAR_ENERGY, CONF_SOLAR_POWER,
)

MISSING = "sensor.vb_not_configured"
_TOKENS = {
    "nordpool": CONF_NORDPOOL, "solar_power": CONF_SOLAR_POWER, "solar_energy": CONF_SOLAR_ENERGY,
    "import_energy": CONF_IMPORT_ENERGY, "export_energy": CONF_EXPORT_ENERGY, "ev_energy": CONF_EV_ENERGY,
    "ev_power": CONF_EV_POWER, "forecast_today": CONF_FORECAST_TODAY, "forecast_tomorrow": CONF_FORECAST_TOMORROW,
}

# kleurenblind-vriendelijk (Okabe-Ito)
BLUE, ORANGE, SKY, PINK = "#0072B2", "#E69F00", "#56B4E9", "#CC79A7"

_S = ("const S = (t) => { const x = new Date(t); const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), "
      "n.getDate(), x.getHours(), x.getMinutes()).getTime(); }; ")
_MIN = "EVAL:(function(){var x=new Date();x.setHours(0,0,0,0);return x.getTime();})()"
_MAX = "EVAL:(function(){var x=new Date();x.setHours(24,0,0,0);return x.getTime();})()"
_XAXIS = {"min": _MIN, "max": _MAX, "tickAmount": 24,
          "labels": {"datetimeUTC": False, "format": "HH:mm", "rotate": -45, "rotateAlways": True}}
_CLICK = ("EVAL:function(){var i=window.__vbHover;if(i==null)return;var h=document.querySelector('home-assistant').hass;"
          "var r=(h.states['@DAY@'].attributes.reeks||[])[i];if(!r)return;var d=new Date(r[0]);"
          "var p=function(n){return (n<10?'0':'')+n;};h.callService('time','set_value',{entity_id:'@TIME@',"
          "time:p(d.getHours())+':'+p(d.getMinutes())+':00'});}")
_TIP = ("EVAL:function(o){var h=document.querySelector('home-assistant').hass;var rs=(h.states['@DAY@'].attributes.reeks)||[];"
        "var r=rs[o.dataPointIndex];window.__vbHover=o.dataPointIndex;if(!r)return '';var d=new Date(r[0]);"
        "var p=function(n){return (n<10?'0':'')+n;};var f=function(v,n){return v==null?'-':Number(v).toFixed(n);};"
        "var pl={L:'laden',O:'ontladen',I:'idle'}[r[10]]||'onbekend';"
        "var so={Z:'laden uit zon',N:'laden van het net',H:'ontladen naar huis',E:'ontladen naar het net',I:'idle'}[r[11]]||'?';"
        "return '<div style=\"padding:8px 10px;line-height:1.5\"><b>'+p(d.getHours())+':'+p(d.getMinutes())+'</b> - '+f(r[1],3)+' euro/kWh"
        "<br>Plan: '+pl+' - werkelijk: '+so+'<br>Geladen '+f(r[2],3)+' - ontladen '+f(r[3],3)+' kWh"
        "<br>Huis excl. auto '+f(r[13]==null?r[4]:r[4]-r[13],3)+' - auto '+f(r[13],3)+' - zon '+f(r[5],3)+' kWh"
        "<br>Afname '+f(r[6],3)+' - terug '+f(r[7],3)+' kWh<br>SoC '+f(r[9],2)+' kWh (plan '+f(r[12],2)+')</div>';}")

_TOTALS = ("{% set t = state_attr('@DAY@','totalen') %}{% if t %}**{{ state_attr('@DAY@','datum') }}** · {{ t.kwartieren }} "
           "kwartieren vastgelegd\n\n| | |\n|---|---|\n| Opbrengst | € {{ '%.2f'|format(t.opbrengst) }} |\n"
           "| Geladen | {{ t.geladen_kwh }} kWh (waarvan zon {{ t.geladen_zon_kwh }}) |\n"
           "| Ontladen | {{ t.ontladen_kwh }} kWh (naar het net {{ t.ontladen_net_kwh }}) |\n"
           "| Huisverbruik | {{ t.huisverbruik_kwh }} kWh{% if t.auto_kwh is not none %} (waarvan auto {{ t.auto_kwh }}){% endif %} |\n"
           "| Zon | {{ t.zon_kwh }} kWh |\n| Afname / teruglevering | {{ t.afname_kwh }} / {{ t.teruglevering_kwh }} kWh |\n"
           "| Prijs gem. (min–max) | {{ '%.3f'|format(t.prijs_gem or 0) }} ({{ t.prijs_min }}–{{ t.prijs_max }}) €/kWh |"
           "{% else %}Geen gegevens voor deze dag.{% endif %}")
_MOMENT = ("{% set m = states.@MOMENT@.attributes %}{% if m.gevonden %}**{{ m.datum }} {{ m.kwartier_start }}** · prijs {{ m.prijs }} €/kWh\n\n"
           "- Plan: {{ {'L':'laden','O':'ontladen','I':'idle'}.get(m.plan_actie, 'onbekend') }} · werkelijk: "
           "{{ {'Z':'laden uit zon','N':'laden van het net','H':'ontladen naar huis','E':'ontladen naar het net','I':'idle'}.get(m.soort,'?') }}\n"
           "- Geladen {{ m.geladen_kwh }} kWh · ontladen {{ m.ontladen_kwh }} kWh\n"
           "- Huis {{ m.huis_kwh }} kWh{% if m.auto_kwh is not none %} (waarvan auto {{ m.auto_kwh }}){% endif %} · zon {{ m.zon_kwh }} kWh\n"
           "- Afname {{ m.afname_kwh }} kWh · teruglevering {{ m.terug_kwh }} kWh\n"
           "- Laadtoestand {{ m.soc }} kWh (plan {{ m.soc_plan if m.soc_plan is not none else '–' }})\n"
           "- Opbrengst kwartier € {{ m.opbrengst }}\n\n_{{ m.reden }}_{% else %}Geen kwartier gevonden voor {{ m.datum }} {{ m.tijd }}.{% endif %}")


def _series(name, typ, color, js, yaxis=None, **extra) -> dict:
    s = {"entity": "@DAY@", "name": name, "type": typ, "color": color, "show": {"legend_value": False},
         "data_generator": _S + "return (entity.attributes.reeks || []).map((r) => " + js + ");"}
    if yaxis:
        s["yaxis_id"] = yaxis
    s.update(extra)
    return s


def _card(title, series, yaxis, apex) -> dict:
    return {"type": "custom:apexcharts-card", "graph_span": "24h", "span": {"start": "day"},
            "header": {"show": True, "show_states": False, "title": title}, "grid_options": {"columns": "full"},
            "apex_config": {"legend": {"show": True}, "xaxis": _XAXIS, **apex}, "yaxis": yaxis, "series": series}


def historie_view() -> dict:
    shared = {"shared": True, "intersect": False, "theme": "dark", "custom": _TIP}
    line = {"extend_to": False, "curve": "straight"}
    c1 = _card("Prijs en laadtoestand van de gekozen dag", [
        _series("Prijs", "line", BLUE, "[S(r[0]), r[1]]", "prijs", stroke_width=2, **{"extend_to": False, "curve": "stepline"}),
        _series("SoC werkelijk", "line", PINK, "[S(r[0]) + 900000, r[9]]", "kwh", stroke_width=3, **line),
        {**_series("SoC volgens plan", "line", ORANGE, "[S(r[0]), r[12]]", "kwh", stroke_width=2, **line),
         "data_generator": _S + "return (entity.attributes.reeks || []).filter((r) => r[12] !== null).map((r) => [S(r[0]), r[12]]);"},
    ], [{"id": "prijs", "decimals": 2, "apex_config": {"title": {"text": "€/kWh"}, "forceNiceScale": True}},
        {"id": "kwh", "opposite": True, "min": 0, "decimals": 1, "apex_config": {"title": {"text": "SoC (kWh)"}}}],
        {"chart": {"height": 300}, "stroke": {"dashArray": [0, 0, 6]}, "tooltip": {"x": {"format": "HH:mm"}}})
    c2 = _card("Laden en ontladen per kwartier (kWh)", [
        _series("Laden uit zon", "column", ORANGE, "[S(r[0]) + 450000, r[11] === 'Z' ? r[2] : 0]"),
        _series("Laden van het net", "column", SKY, "[S(r[0]) + 450000, r[11] === 'N' ? r[2] : 0]"),
        _series("Ontladen naar huis", "column", BLUE, "[S(r[0]) + 450000, r[11] === 'H' ? -r[3] : 0]"),
        _series("Ontladen naar het net", "column", PINK, "[S(r[0]) + 450000, r[11] === 'E' ? -r[3] : 0]"),
    ], [{"decimals": 2, "apex_config": {"title": {"text": "kWh per kwartier (− = ontladen)"}, "forceNiceScale": True}}],
        {"chart": {"height": 300, "stacked": True, "events": {"click": _CLICK}}, "dataLabels": {"enabled": False},
         "plotOptions": {"bar": {"columnWidth": "90%"}}, "tooltip": shared})
    c3 = _card("Zon, huisverbruik en opbrengst van de gekozen dag", [
        _series("Zon", "column", ORANGE, "[S(r[0]) + 450000, r[5]]", "kwh"),
        _series("Huisverbruik (excl. auto)", "column", BLUE, "[S(r[0]) + 450000, Math.max(0, r[4] - (r[13] || 0))]", "kwh"),
        _series("Auto laden", "column", SKY, "[S(r[0]) + 450000, r[13] || 0]", "kwh"),
        _series("Opbrengst (cumulatief)", "line", PINK, "[S(r[0]) + 900000, r[8]]", "eur", **line),
    ], [{"id": "kwh", "min": 0, "decimals": 2, "apex_config": {"title": {"text": "kWh per kwartier"}}},
        {"id": "eur", "opposite": True, "decimals": 2, "apex_config": {"title": {"text": "Opbrengst (€, cumulatief)"}}}],
        {"chart": {"height": 300, "events": {"click": _CLICK}}, "dataLabels": {"enabled": False},
         "plotOptions": {"bar": {"columnWidth": "90%"}}, "stroke": {"width": [0, 0, 0, 3]}, "tooltip": shared})
    return {"title": "Historie", "path": "historie", "icon": "mdi:calendar-search", "type": "sections", "max_columns": 3,
            "sections": [
                {"type": "grid", "cards": [
                    {"type": "heading", "heading": "Kies dag en tijd", "icon": "mdi:calendar-search"},
                    {"type": "tile", "entity": "@DATE@", "name": "Datum", "grid_options": {"columns": 6}, "features": [{"type": "date-set"}]},
                    {"type": "tile", "entity": "@TIME@", "name": "Tijd (kwartier)", "grid_options": {"columns": 6}},
                    {"type": "tile", "entity": "@DAY@", "name": "Opbrengst gekozen dag", "grid_options": {"columns": 6}},
                    {"type": "tile", "entity": "@MOMENT@", "name": "Vermogen in gekozen kwartier", "grid_options": {"columns": 6}},
                    {"type": "markdown", "title": "Totalen van de dag", "grid_options": {"columns": 12}, "content": _TOTALS},
                    {"type": "markdown", "title": "Gekozen kwartier", "grid_options": {"columns": 12}, "content": _MOMENT}]},
                {"type": "grid", "column_span": 2, "cards": [c1, c2, c3]}]}


def _walk(x: Any, fn) -> Any:
    if isinstance(x, dict):
        return {k: _walk(v, fn) for k, v in x.items()}
    if isinstance(x, list):
        return [_walk(v, fn) for v in x]
    return fn(x) if isinstance(x, str) else x


def _prune(x: Any) -> Any:
    """Verwijder tegels/kaarten die naar een niet-ingestelde (optionele) sensor wijzen."""
    if isinstance(x, dict):
        return {k: _prune(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_prune(v) for v in x if not (isinstance(v, dict) and v.get("type") in ("tile", "entity") and v.get("entity") == MISSING)]
    return x


def build_dashboard(cfg: dict[str, Any]) -> dict[str, Any]:
    """Lovelace-configuratie (views) met de entiteiten van deze installatie ingevuld."""
    slug = slugify(cfg.get(CONF_NAME, "virtual_battery"))
    views = json.loads(Path(__file__).with_name("views.json").read_text(encoding="utf-8"))
    views.append(historie_view())
    ext = {f"@@{t}@@": (cfg.get(c) or MISSING) for t, c in _TOKENS.items()}
    own = {"@DAY@": f"sensor.{slug}_day_view", "@MOMENT@": f"sensor.{slug}_moment_view",
           "@DATE@": f"date.{slug}_view_date", "@TIME@": f"time.{slug}_view_time"}
    pat = re.compile(r"\b(sensor|number|select|date|time)\.virtual_battery_")

    def fix(s: str) -> str:
        for k, v in {**ext, **own}.items():
            s = s.replace(k, v)
        return pat.sub(lambda m: f"{m.group(1)}.{slug}_", s)

    cfg_out = {"views": _prune(_walk(views, fix))}
    cfg_out["views"][0]["title"] = cfg.get(CONF_NAME, "Virtual battery")
    return cfg_out
