"""Coördinator: verzamelt invoer uit Home Assistant en laat de rekenmodules draaien."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State as HAState, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_change, async_track_time_interval
from homeassistant.helpers.storage import Store

from .archive_store import ArchiveStore
from .const import (
    CONF_CAPACITY, CONF_DEPRECIATION, CONF_EV_ENERGY, CONF_EV_POWER, CONF_EXPORT_ENERGY, CONF_FEED_IN,
    CONF_FORECAST_REMAINING, CONF_FORECAST_TODAY, CONF_FORECAST_TOMORROW, CONF_GRID_EXPORT, CONF_GRID_IMPORT,
    CONF_IMPORT_ENERGY, CONF_MAX_POWER, CONF_NORDPOOL, CONF_PRICE, CONF_SOLAR_ENERGY, CONF_SOLAR_POWER,
    DEFAULT_EV_POLICY, DEFAULT_STRATEGY, DOMAIN, EV_POLICIES, LEGACY_OPTIONS, NUMBER_SETTINGS, PROFILE_KEYS, REPLAN_DELAY_SECONDS, REPLAN_KEYS, STRATEGIES, TICK_SECONDS,
)
from .logic import consumption_profile as cp
from .logic import forecast as fc
from .logic import zon_log
from .logic import archive as arch
from .logic.engine import Block, Inputs, State as EngineState, engine_tick
from .logic.planner import AMS, Params, make_consumption_fn, parse_prices, plan_day
from .logic.simulation import SimBlock, SimInputs, simulate

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
UNAVAILABLE = ("unknown", "unavailable", "", None)


def _to_ms(v: Any) -> int | None:
    """Recorder-statistieken: start kan seconden (float) of milliseconden zijn."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return int(v.timestamp() * 1000)
    v = float(v)
    return int(v * 1000) if v < 1e11 else int(v)


def _num(state: HAState | None, default: float | None = None) -> float | None:
    if state is None or state.state in UNAVAILABLE:
        return default
    try:
        return float(state.state)
    except ValueError:
        return default


def _power_w(state: HAState | None, default: float = 0.0) -> float:
    v = _num(state, None)
    if v is None:
        return default
    unit = state.attributes.get("unit_of_measurement")
    if unit == "kW":
        return v * 1000
    if unit == "MW":
        return v * 1_000_000
    return v


def _iso(v: Any) -> str:
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


class VirtualBatteryCoordinator:
    """Keeps the state of the virtual battery and publishes it to the entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.cfg: dict[str, Any] = {**entry.data, **entry.options}
        self.store: Store = Store(hass, STORE_VERSION, f"virtual_battery.{entry.entry_id}")

        # instellingen (entiteiten lezen en schrijven hier)
        self.settings: dict[str, Any] = {k: v[4] for k, v in NUMBER_SETTINGS.items()}
        self.settings["capacity"] = float(self.cfg.get(CONF_CAPACITY, self.settings["capacity"]))
        self.settings["max_power"] = float(self.cfg.get(CONF_MAX_POWER, self.settings["max_power"]))
        self.settings["depreciation"] = float(self.cfg.get(CONF_DEPRECIATION, self.settings["depreciation"]))
        self.settings["feed_in_discount"] = float(self.cfg.get(CONF_FEED_IN, self.settings["feed_in_discount"]))
        self.settings["strategy"] = DEFAULT_STRATEGY
        self.settings["ev_policy"] = DEFAULT_EV_POLICY

        # rekenstaat
        self.engine_state = EngineState()
        self.outputs: dict[str, Any] = {}
        self.schedule: dict[int, dict] = {}
        self.plan_info: dict[str, Any] = {}
        self.solar_raw: dict[int, float] = {}
        self.solar_corr: dict[int, float] = {}
        self.solar_sensor: dict[str, Any] = {}
        self.profile: list | None = None
        self.profile_info: dict[str, Any] = {}
        self.sim: dict[str, Any] = {}
        self.nowcast: dict[str, Any] = {}
        self.restored: dict[str, Any] = {}
        self.day: str | None = None

        # dagarchief + weergavekeuze (datum/tijd)
        self.archive = ArchiveStore(hass, entry.entry_id)
        self.acc: arch.QuarterAcc | None = None
        self._last_arch_ms = 0
        self.view_date: str | None = None      # None = vandaag volgen
        self.view_time: str | None = None      # None = huidig kwartier volgen (HH:MM)
        self._imported = False
        self._day_cache: tuple | None = None
        self._arch_save_unsub: CALLBACK_TYPE | None = None

        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._replan_unsub: CALLBACK_TYPE | None = None
        self._profile_unsub: CALLBACK_TYPE | None = None
        self._plan_lock = asyncio.Lock()
        self._tick_running = False
        self._last_tick_ms = 0.0
        self._save_unsub: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------------ levenscyclus
    async def async_setup(self) -> None:
        data = await self.store.async_load() or {}
        for k, v in (data.get("settings") or {}).items():
            if k in self.settings:
                self.settings[k] = LEGACY_OPTIONS.get(v, v) if k in ("strategy", "ev_policy") else v
        if self.settings["strategy"] not in STRATEGIES:
            self.settings["strategy"] = DEFAULT_STRATEGY
        if self.settings["ev_policy"] not in EV_POLICIES:
            self.settings["ev_policy"] = DEFAULT_EV_POLICY
        self.restored = {"soc": data.get("soc"), "total": data.get("total"), "today": data.get("today"), "avgcost": data.get("avgcost")}
        self.day = data.get("day")
        self.view_date = data.get("view_date")
        self.view_time = data.get("view_time")
        self._imported = data.get("imported") == 3
        if data.get("acc"):
            try:
                self.acc = arch.QuarterAcc.from_dict(data["acc"])
                if not 0 <= self.acc.solar <= arch.SOLAR_MAX_W / 1000 * 0.25:
                    self.acc.solar = 0.0
            except (KeyError, TypeError):
                self.acc = None
        now_ms = int(time.time() * 1000)
        await self.archive.async_load_day(arch.day_of(now_ms))
        await self.archive.async_load_day(self.view_date or arch.day_of(now_ms))
        if data.get("profile"):
            self.profile = data["profile"]

    @callback
    def async_start(self) -> None:
        hass = self.hass
        self._unsubs.append(async_track_time_interval(hass, self._async_tick, timedelta(seconds=TICK_SECONDS)))
        self._unsubs.append(async_track_time_change(hass, self._async_quarter, minute=list(range(0, 60, 5)), second=0))
        self._unsubs.append(async_track_time_change(hass, self._async_hourly, minute=5, second=0))
        self._unsubs.append(async_track_time_change(hass, self._async_log_forecast, hour=6, minute=0, second=0))
        self._unsubs.append(async_track_time_change(hass, self._async_log_actual, hour=0, minute=5, second=0))
        self._unsubs.append(async_track_time_change(hass, self._async_purge_archive, hour=3, minute=10, second=0))
        self._unsubs.append(async_track_state_change_event(hass, [self.cfg[CONF_NORDPOOL]], self._async_prices_changed))
        self.entry.async_create_background_task(hass, self._async_initial(), "virtual_battery_initial")

    async def _async_initial(self) -> None:
        await self.async_refresh_profile()
        await self.async_replan()
        if not self._imported:
            await self.async_import_history(10)

    async def async_shutdown(self) -> None:
        for u in self._unsubs:
            u()
        self._unsubs.clear()
        for u in (self._replan_unsub, self._profile_unsub, self._save_unsub):
            if u:
                u()
        if self._arch_save_unsub:
            self._arch_save_unsub()
        await self.store.async_save(self._data_to_save())
        await self.archive.async_save()

    # ------------------------------------------------------------------ pub/sub naar entiteiten
    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> CALLBACK_TYPE:
        self._listeners.append(update)

        def _remove() -> None:
            if update in self._listeners:
                self._listeners.remove(update)

        return _remove

    @callback
    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # ------------------------------------------------------------------ instellingen
    @callback
    def async_set_setting(self, key: str, value: Any) -> None:
        if self.settings.get(key) == value:
            return
        self.settings[key] = value
        self._request_save(5, urgent=True)
        self._notify()
        if key in REPLAN_KEYS:
            self._schedule_replan()
        if key in PROFILE_KEYS:
            self._schedule_profile()

    @callback
    def _schedule_replan(self) -> None:
        if self._replan_unsub:
            self._replan_unsub()
        self._replan_unsub = async_call_later(self.hass, REPLAN_DELAY_SECONDS, self._async_replan_cb)

    @callback
    def _schedule_profile(self) -> None:
        if self._profile_unsub:
            self._profile_unsub()
        self._profile_unsub = async_call_later(self.hass, REPLAN_DELAY_SECONDS, self._async_profile_cb)

    async def _async_replan_cb(self, _now: datetime) -> None:
        self._replan_unsub = None
        await self.async_replan()

    async def _async_profile_cb(self, _now: datetime) -> None:
        self._profile_unsub = None
        await self.async_refresh_profile()
        await self.async_replan()

    @callback
    def _request_save(self, delay: float = 60, urgent: bool = False) -> None:
        """Opslaan met vertraging; een lopende timer wordt niet steeds opgeschoven (anders schrijft de 2-s tick nooit weg)."""
        if self._save_unsub is not None:
            if not urgent:
                return
            self._save_unsub()
        self._save_unsub = async_call_later(self.hass, delay, self._async_do_save)

    async def _async_do_save(self, _now: datetime) -> None:
        self._save_unsub = None
        await self.store.async_save(self._data_to_save())

    def _data_to_save(self) -> dict[str, Any]:
        st = self.engine_state
        return {
            "settings": self.settings,
            "soc": st.soc if st.soc is not None else self.restored.get("soc"),
            "total": st.total if st.total is not None else self.restored.get("total"),
            "today": st.today if st.today is not None else self.restored.get("today"),
            "avgcost": st.avgcost if st.avgcost is not None else self.restored.get("avgcost"),
            "day": self.day,
            "profile": self.profile,
            "view_date": self.view_date,
            "view_time": self.view_time,
            "imported": 3 if self._imported else 0,
            "acc": self.acc.to_dict() if self.acc else None,
        }

    # ------------------------------------------------------------------ invoer lezen
    def _state(self, key: str) -> HAState | None:
        eid = self.cfg.get(key)
        return self.hass.states.get(eid) if eid else None

    def _nordpool_raw(self) -> tuple[list[dict], bool]:
        st = self._state(CONF_NORDPOOL)
        if st is None:
            return [], False
        a = st.attributes
        valid = bool(a.get("tomorrow_valid"))
        today = [{"start": _iso(h["start"]), "end": _iso(h["end"]), "value": h.get("value")} for h in (a.get("raw_today") or [])]
        tomorrow = [{"start": _iso(h["start"]), "end": _iso(h["end"]), "value": h.get("value")} for h in (a.get("raw_tomorrow") or [])] if valid else []
        return today + tomorrow, valid

    def _blocks(self) -> list[Block]:
        raw, _ = self._nordpool_raw()
        out = []
        for h in raw:
            try:
                s = datetime.fromisoformat(h["start"])
                e = datetime.fromisoformat(h["end"])
            except ValueError:
                continue
            dur = (e - s).total_seconds() / 3600
            out.append(Block(key=int(round(s.timestamp() * 1000)), start_iso=s.astimezone(AMS).isoformat(),
                             price=None if h["value"] is None else float(h["value"]), dur_h=dur if dur > 0 else 0.25))
        return out

    def _current_price(self) -> float:
        st = self._state(CONF_PRICE) or self._state(CONF_NORDPOOL)
        return _num(st, 0.0) or 0.0

    def _solar_factor(self) -> float:
        return fc.solar_factor(self.settings["solar_certainty"])

    def _wear_per_kwh(self) -> float:
        cap = max(1.0, min(100.0, self.settings["capacity"]))
        return max(0.0, self.settings["depreciation"] / 100) / cap

    # ------------------------------------------------------------------ 2-seconden tick (engine)
    async def _async_tick(self, _now: datetime) -> None:
        if self._tick_running:
            return
        self._tick_running = True
        try:
            now_ms = int(time.time() * 1000)
            today = fc.day_of(now_ms)
            st = self.engine_state
            if self.day is not None and self.day != today:
                st.today = 0.0          # dagwissel: dagopbrengst terug op 0
            self.day = today
            r = self.restored
            inp = Inputs(
                now_ms=now_ms,
                strategy=self.settings["strategy"],
                ev_policy=self.settings["ev_policy"],
                lang="nl" if str(self.hass.config.language).lower().startswith("nl") else "en",
                price=self._current_price(),
                feed_in_discount=self.settings["feed_in_discount"],
                max_margin=self.settings["max_margin"],
                grid_import_w=_power_w(self._state(CONF_GRID_IMPORT)),
                grid_export_w=_power_w(self._state(CONF_GRID_EXPORT)),
                wallconnector_kw=_power_w(self._state(CONF_EV_POWER)) / 1000,
                solar_w=_power_w(self._state(CONF_SOLAR_POWER), float("nan")),
                solar_remaining_today_kwh=_num(self._state(CONF_FORECAST_REMAINING)),
                base_load_fallback_w=self.profile_info.get("fallback_w", 400.0),
                profile=self.profile,
                cap_kwh=self.settings["capacity"],
                min_soc_pct=self.settings["min_soc"],
                max_kw=self.settings["max_power"],
                depreciation_per_cycle=self.settings["depreciation"] / 100,
                ha_soc=st.soc if st.soc is not None else (r.get("soc") or 0.0),
                ha_total=st.total if st.total is not None else (r.get("total") or 0.0),
                ha_today=st.today if st.today is not None else (r.get("today") or 0.0),
                ha_avgcost=st.avgcost if st.avgcost is not None else (r.get("avgcost") or 0.0),
                blocks=self._blocks(),
                schedule=self.schedule,
                solar_map=self.solar_corr,
                solar_factor=self._solar_factor(),
            )
            self.outputs = await self.hass.async_add_executor_job(engine_tick, inp, st)
            await self._archive_tick(now_ms, inp)
            self._notify()
            self._request_save()
        except Exception:  # noqa: BLE001 - de tick moet nooit stoppen
            _LOGGER.exception("Fout in engine-tick")
        finally:
            self._tick_running = False

    # ------------------------------------------------------------------ dagarchief
    def _plan_char(self, key: int) -> str:
        a = (self.schedule.get(key) or {}).get("action")
        return {"laden": "L", "ontladen": "O"}.get(a, "I")

    def _soc_plan_at(self, key: int) -> float | None:
        best = None
        for t, v in self.sim.get("soc_reeks") or []:
            if abs(t - key) <= 450000 and (best is None or abs(t - key) < abs(best[0] - key)):
                best = (t, v)
        return best[1] if best else None

    async def _archive_tick(self, now_ms: int, inp: Inputs) -> None:
        key = arch.quarter_start(now_ms)
        if self.acc is not None and self.acc.key != key:
            await self._finalize_acc()
        if self.acc is None:
            self.acc = arch.QuarterAcc(key, inp.price, self._plan_char(key), self._soc_plan_at(key))
            self._last_arch_ms = 0
        dt = (now_ms - self._last_arch_ms) / 1000 if self._last_arch_ms else 0.0
        self._last_arch_ms = now_ms
        solar = inp.solar_w if inp.solar_w == inp.solar_w else None
        self.acc.add(dt, self.outputs, solar, inp.wallconnector_kw * 1000)

    async def _finalize_acc(self) -> None:
        acc, self.acc = self.acc, None
        if acc is None or acc.seconds < 60:
            return
        await self.archive.async_add_rows([acc.to_row()], overwrite=True)
        if self._arch_save_unsub is None:
            self._arch_save_unsub = async_call_later(self.hass, 30, self._async_save_archive)

    async def _async_save_archive(self, _now: datetime) -> None:
        self._arch_save_unsub = None
        await self.archive.async_save()

    async def _async_purge_archive(self, _now: datetime) -> None:
        await self.archive.async_purge()
        await self.archive.async_save()

    # ------------------------------------------------------------------ weergave: gekozen dag en tijdstip
    def view_day(self) -> str:
        return self.view_date or arch.day_of(time.time() * 1000)

    def view_hhmm(self) -> str:
        if self.view_time:
            return self.view_time
        return datetime.now(AMS).strftime("%H:%M")

    async def async_set_view_date(self, day: str | None) -> None:
        if day == arch.day_of(time.time() * 1000):
            day = None
        if day:
            await self.archive.async_load_day(day)
        self.view_date = day
        self._request_save(5, urgent=True)
        self._notify()

    @callback
    def async_set_view_time(self, hhmm: str | None) -> None:
        self.view_time = hhmm
        self._request_save(5, urgent=True)
        self._notify()

    def day_view_data(self) -> dict:
        day = self.view_day()
        sig = (day, self.archive.version)
        if self._day_cache is None or self._day_cache[0] != sig:
            self._day_cache = (sig, arch.day_view(self.archive.rows_for_day(day), day))
        return self._day_cache[1]

    def moment_data(self) -> dict:
        day, hhmm = self.view_day(), self.view_hhmm()
        row = arch.moment_row(self.archive.rows_for_day(day), day, hhmm)
        if row is None and self.acc is not None and day == arch.day_of(self.acc.key):
            live = self.acc.to_row()
            if arch.moment_row([live], day, hhmm):
                row = live
        out: dict = {"datum": day, "tijd": hhmm, "gevonden": row is not None}
        if row is not None:
            g = {c: arch.val(row, c) for c in arch.COLS}
            q = 0.25
            out.update({
                "kwartier_start": datetime.fromtimestamp(g["t"] / 1000, AMS).strftime("%H:%M"),
                "prijs": g["price"], "plan_actie": g["plan"], "soort": g["kind"], "soc": g["soc"], "soc_plan": g["soc_plan"],
                "reden": g["reason"], "huis_kwh": g["house"], "auto_kwh": g["ev"],
                "huis_excl_auto_kwh": None if g["ev"] is None else round((g["house"] or 0) - g["ev"], 4), "zon_kwh": g["solar"], "geladen_kwh": g["charge"],
                "ontladen_kwh": g["discharge"], "afname_kwh": g["imp"], "terug_kwh": g["exp"], "opbrengst": g["rev"],
                "vermogen_w": round(((g["charge"] or 0) - (g["discharge"] or 0)) / q * 1000),
            })
        return out

    # ------------------------------------------------------------------ historie uit de recorder inladen
    def _own_entity(self, key: str) -> str | None:
        from homeassistant.helpers import entity_registry as er
        return er.async_get(self.hass).async_get_entity_id("sensor", DOMAIN, f"{self.entry.entry_id}_{key}")

    async def async_import_history(self, days: int = 10) -> int:
        """Vul het archief met kwartieren uit de recorder-historie (bestaande kwartieren blijven staan)."""
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states

        days = max(1, min(int(days), 60))
        num_map = {"charge_power": "charge_w", "discharge_power": "discharge_w", "house_consumption": "house_w",
                   "effective_import": "imp_w", "effective_export": "exp_w", "soc": "soc", "revenue_total": "rev_total"}
        ids: dict[str, str] = {}
        for key, name in num_map.items():
            eid = self._own_entity(key)
            if eid:
                ids[name] = eid
        if "charge_w" not in ids or "soc" not in ids:
            return 0
        reason_id = self._own_entity("reason")
        if self.cfg.get(CONF_SOLAR_POWER):
            ids["solar_w"] = self.cfg[CONF_SOLAR_POWER]
        if self.cfg.get(CONF_EV_POWER):
            ids["ev_w"] = self.cfg[CONF_EV_POWER]
        ev_factor = {"kW": 1000.0, "MW": 1_000_000.0}.get((self._state(CONF_EV_POWER).attributes.get("unit_of_measurement") if self._state(CONF_EV_POWER) else None), 1.0)
        ids["price"] = self.cfg.get(CONF_PRICE) or self.cfg[CONF_NORDPOOL]
        all_ids = list(ids.values()) + ([reason_id] if reason_id else [])
        now_ms = int(time.time() * 1000)
        end_total = arch.quarter_start(now_ms)
        start_total = arch.quarter_start(now_ms - days * 86_400_000)
        added = 0
        t0 = start_total
        while t0 < end_total:
            t1 = min(t0 + 86_400_000, end_total)
            start = datetime.fromtimestamp(t0 / 1000, timezone.utc)
            end = datetime.fromtimestamp(t1 / 1000, timezone.utc)
            try:
                res = await get_instance(self.hass).async_add_executor_job(
                    lambda: get_significant_states(self.hass, start, end, all_ids, include_start_time_state=True,
                                                   significant_changes_only=False, no_attributes=True))
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Historie ophalen mislukt")
                return added
            num: dict[str, list] = {}
            for name, eid in ids.items():
                pts = []
                for st in res.get(eid, []):
                    try:
                        v = float(st.state)
                    except (TypeError, ValueError):
                        continue
                    ts = st.last_updated.timestamp() * 1000 if st.last_updated else t0
                    pts.append((int(max(ts, t0)), v * (ev_factor if name == "ev_w" else 1.0)))
                num[name] = sorted(pts)
            txt = {"reason": sorted((int(max(st.last_updated.timestamp() * 1000, t0)), st.state)
                                    for st in res.get(reason_id, []) if st.state not in ("unknown", "unavailable"))} if reason_id else {}
            rows = await self.hass.async_add_executor_job(arch.rows_from_history, num, txt, t0, t1)
            for r in rows:                       # kwartieren met foutieve zonwaarde herstellen (plan/soc_plan behouden)
                oud = self.archive.get_row(r[0])
                if oud is not None and arch.needs_repair(oud):
                    r[arch.IDX["plan"]], r[arch.IDX["soc_plan"]] = oud[arch.IDX["plan"]], oud[arch.IDX["soc_plan"]]
                    await self.archive.async_add_rows([r], overwrite=True)
                    added += 1
            added += await self.archive.async_add_rows(rows)
            t0 = t1
        self._imported = True
        await self.archive.async_save()
        self._request_save(2, urgent=True)
        self._notify()
        _LOGGER.info("Historie ingeladen: %s kwartieren", added)
        return added

    # ------------------------------------------------------------------ periodieke taken
    async def _async_quarter(self, _now: datetime) -> None:
        await self.async_replan()

    async def _async_hourly(self, _now: datetime) -> None:
        await self.async_refresh_profile()

    async def _async_prices_changed(self, event: Event) -> None:
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if old is None or new is None:
            return
        keys = ("raw_today", "raw_tomorrow", "tomorrow_valid")
        if any(old.attributes.get(k) != new.attributes.get(k) for k in keys):
            self._schedule_replan()

    # ------------------------------------------------------------------ statistieken
    async def _stats(self, ids: list[str], start: datetime, end: datetime) -> dict[str, list[dict]]:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period

        ids = [i for i in ids if i]
        if not ids:
            return {}
        try:
            return await get_instance(self.hass).async_add_executor_job(
                statistics_during_period, self.hass, start, end, set(ids), "hour", None, {"change"})
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Statistieken ophalen mislukt")
            return {}

    @staticmethod
    def _changes(rows: list[dict] | None) -> dict[int, float]:
        out: dict[int, float] = {}
        for r in rows or []:
            ms, ch = _to_ms(r.get("start")), r.get("change")
            if ms is not None and ch is not None:
                out[ms] = float(ch)
        return out

    # ------------------------------------------------------------------ verbruiksprofiel (uurlijks)
    async def async_refresh_profile(self) -> None:
        sid = {cp.PV: self.cfg.get(CONF_SOLAR_ENERGY), cp.IMPORT: self.cfg.get(CONF_IMPORT_ENERGY),
               cp.EXPORT: self.cfg.get(CONF_EXPORT_ENERGY), cp.CAR: self.cfg.get(CONF_EV_ENERGY)}
        now_ms = int(time.time() * 1000)
        weeks = self.settings["profile_weeks"]
        end_ms, begin_ms = cp.window(now_ms, weeks)
        res = await self._stats(list(sid.values()), datetime.fromtimestamp(begin_ms / 1000, timezone.utc),
                                datetime.fromtimestamp(end_ms / 1000, timezone.utc))
        if not res:
            return
        series = {k: self._changes(res.get(v)) for k, v in sid.items() if v}
        fallback = self.profile_info.get("fallback_w", 400.0)
        profile, det = await self.hass.async_add_executor_job(
            cp.compute_profile, series, end_ms, weeks, self.settings["profile_weight_last"],
            self.settings["profile_mix"], fallback, now_ms)
        if det["hours_used"] == 0:
            return
        self.profile = profile
        self.profile_info = {**det, "fallback_w": fallback, "updated": datetime.now(timezone.utc).isoformat()}
        self._request_save(10)
        self._notify()

    # ------------------------------------------------------------------ plannen (elke 5 minuten / bij wijziging)
    async def async_replan(self) -> None:
        async with self._plan_lock:
            try:
                await self._replan()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Herberekenen mislukt")

    async def _replan(self) -> None:
        now_ms = int(time.time() * 1000)
        # 1. zonvoorspelling + nowcast
        a_today = (self._state(CONF_FORECAST_TODAY).attributes.get("wh_period_15m") if self._state(CONF_FORECAST_TODAY) else None)
        a_tom = (self._state(CONF_FORECAST_TOMORROW).attributes.get("wh_period_15m") if self._state(CONF_FORECAST_TOMORROW) else None)
        raw = fc.parse_forecast({str(k): v for k, v in (a_today or {}).items()}, {str(k): v for k, v in (a_tom or {}).items()})
        if raw:
            hour = (now_ms // 3600000) * 3600000
            res = await self._stats([self.cfg.get(CONF_SOLAR_ENERGY)], datetime.fromtimestamp((hour - 30 * 3600000) / 1000, timezone.utc),
                                    datetime.fromtimestamp(hour / 1000, timezone.utc))
            actual = self._changes(res.get(self.cfg.get(CONF_SOLAR_ENERGY)))
            nc = fc.nowcast(raw, actual, now_ms)
            self.solar_raw, self.solar_corr = raw, nc["corr"]
            self.solar_sensor = fc.hourly_sensor(raw, nc["corr"], nc["ratio"], nc["hours_used"], now_ms)
            self.nowcast = nc
        # 2. dagschema
        raw_prices, tomorrow_valid = self._nordpool_raw()
        hours = parse_prices(raw_prices, [], False)
        profile_fn = make_consumption_fn(self.profile, self.profile_info.get("fallback_w", 400.0))
        params = Params(
            capacity_kwh=self.settings["capacity"], min_soc_pct=self.settings["min_soc"], max_power_kw=self.settings["max_power"],
            wear_per_kwh=self._wear_per_kwh(), feed_in_discount=self.settings["feed_in_discount"],
            min_margin=self.settings["min_margin"],
            start_soc=self.engine_state.soc if self.engine_state.soc is not None else (self.restored.get("soc") or 0.0),
            solar_factor=self._solar_factor(), base_load_w=self.profile_info.get("fallback_w", 400.0))
        result = await self.hass.async_add_executor_job(
            plan_day, hours, params, now_ms, profile_fn, self.solar_corr, self.schedule)
        self.schedule = result.schedule
        self.plan_info = {"plan": result.plan, "solar_surplus_kwh": round(result.solar_surplus_kwh, 2), "blocks": result.n_blocks}
        # 3. verwachte opbrengst
        blocks = []
        for h in raw_prices:
            if h["value"] is None:
                continue
            s = datetime.fromisoformat(h["start"])
            e = datetime.fromisoformat(h["end"])
            key = int(round(s.timestamp() * 1000))
            dur = (e - s).total_seconds() / 3600
            blocks.append(SimBlock(key=key, end_ms=int(round(e.timestamp() * 1000)) if dur > 0 else key + 900000,
                                   price=float(h["value"]), dur_h=dur if dur > 0 else 0.25, plan=self.schedule.get(key)))
        blocks.sort(key=lambda b: b.key)
        st = self.engine_state
        sim_in = SimInputs(
            now_ms=now_ms, strategy=self.settings["strategy"], feed_in_discount=self.settings["feed_in_discount"],
            max_margin=self.settings["max_margin"],
            soc_kwh=st.soc if st.soc is not None else (self.restored.get("soc") or 0.0),
            realised_today=st.today if st.today is not None else (self.restored.get("today") or 0.0),
            cap_kwh=self.settings["capacity"], max_power_w=self.settings["max_power"] * 1000,
            wear_per_kwh=self._wear_per_kwh(), profile=self.profile,
            base_load_fallback_w=self.profile_info.get("fallback_w", 400.0), solar_map=self.solar_corr,
            solar_factor=self._solar_factor(), blocks=blocks, tomorrow_valid=tomorrow_valid, min_soc_pct=self.settings["min_soc"])
        self.sim = await self.hass.async_add_executor_job(simulate, sim_in)
        self.sim["calculated_at"] = datetime.now(timezone.utc).isoformat()
        self._notify()

    # ------------------------------------------------------------------ log
    def _log_path(self) -> str:
        return self.hass.config.path("virtual_battery", "zon_log.jsonl")

    async def _append_log(self, line: str | None) -> None:
        if not line:
            return
        path = self._log_path()

        def _write() -> None:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

        await self.hass.async_add_executor_job(_write)

    async def _async_log_forecast(self, _now: datetime) -> None:
        await self._append_log(zon_log.forecast_record(self.solar_raw, self._solar_factor(), int(time.time() * 1000)))

    async def _async_log_actual(self, _now: datetime) -> None:
        now_ms = int(time.time() * 1000)
        hour = (now_ms // 3600000) * 3600000
        ids = {"pv": self.cfg.get(CONF_SOLAR_ENERGY), "imp": self.cfg.get(CONF_IMPORT_ENERGY),
               "exp": self.cfg.get(CONF_EXPORT_ENERGY), "car": self.cfg.get(CONF_EV_ENERGY)}
        res = await self._stats(list(ids.values()), datetime.fromtimestamp((hour - 48 * 3600000) / 1000, timezone.utc),
                                datetime.fromtimestamp(hour / 1000, timezone.utc))
        if not res:
            return
        s = {k: self._changes(res.get(v)) for k, v in ids.items()}
        await self._append_log(zon_log.actual_record(s["pv"], s["imp"], s["exp"], s["car"], now_ms))
