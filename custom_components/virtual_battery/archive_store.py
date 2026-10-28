"""Opslag van het kwartierarchief: één bestand per maand in .storage (2 jaar bewaard)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .logic.archive import RETENTION_DAYS, day_of, month_of
from .logic.planner import AMS

ARCHIVE_STORE_VERSION = 1


class ArchiveStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._stores: dict[str, Store] = {}
        self._months: dict[str, dict[int, list]] = {}      # maand -> {t: rij}
        self._dirty: set[str] = set()
        self._cache: dict[str, tuple] = {}
        self.version = 0                                    # verhoogt bij elke wijziging (sensoren verversen)

    def _store(self, month: str) -> Store:
        if month not in self._stores:
            self._stores[month] = Store(self._hass, ARCHIVE_STORE_VERSION, f"virtual_battery.{self._entry_id}.archive.{month}")
        return self._stores[month]

    async def async_load_month(self, month: str) -> None:
        if month in self._months:
            return
        data = await self._store(month).async_load() or {}
        self._months[month] = {int(r[0]): r for r in data.get("rows", [])}

    async def async_load_day(self, day: str) -> None:
        await self.async_load_month(month_of(day))

    def rows_for_day(self, day: str) -> list[list]:
        c = self._cache.get(day)
        if c and c[0] == self.version:
            return c[1]
        m = self._months.get(month_of(day), {})
        rows = sorted((r for r in m.values() if day_of(r[0]) == day), key=lambda r: r[0])
        self._cache[day] = (self.version, rows)
        return rows

    def get_row(self, t: int):
        return self._months.get(month_of(day_of(t)), {}).get(int(t))

    def rows_with_bad_solar(self) -> list[list]:
        from .logic.archive import solar_invalid
        return [r for m in self._months.values() for r in m.values() if solar_invalid(r)]

    def has_row(self, t: int) -> bool:
        return t in self._months.get(month_of(day_of(t)), {})

    async def async_add_rows(self, rows: list[list], overwrite: bool = False) -> int:
        n = 0
        for r in rows:
            mo = month_of(day_of(r[0]))
            await self.async_load_month(mo)
            if int(r[0]) in self._months[mo] and not overwrite:
                continue
            self._months[mo][int(r[0])] = r
            self._dirty.add(mo)
            n += 1
        if n:
            self.version += 1
        return n

    async def async_save(self) -> None:
        for mo in list(self._dirty):
            self._dirty.discard(mo)
            rows = sorted(self._months[mo].values(), key=lambda r: r[0])
            await self._store(mo).async_save({"rows": rows})

    async def async_purge(self, now_ms: int | None = None) -> None:
        """Verwijder maanden waarvan de laatste dag ouder is dan de bewaartermijn."""
        now = datetime.fromtimestamp((now_ms or time.time() * 1000) / 1000, AMS)
        grens = now - timedelta(days=RETENTION_DAYS)
        d = grens.replace(day=1)
        oud = {m for m in self._months if m < d.strftime("%Y-%m")}
        for _ in range(6):
            d = (d - timedelta(days=1)).replace(day=1)
            oud.add(d.strftime("%Y-%m"))
        for mo in sorted(oud):
            self._months.pop(mo, None)
            self._dirty.discard(mo)
            await self._store(mo).async_remove()
        # binnen de grensmaand: oude kwartieren weghalen
        mo = grens.strftime("%Y-%m")
        if mo in self._months:
            ms = int(grens.timestamp() * 1000)
            oud = [t for t in self._months[mo] if t < ms]
            for t in oud:
                del self._months[mo][t]
            if oud:
                self._dirty.add(mo)
