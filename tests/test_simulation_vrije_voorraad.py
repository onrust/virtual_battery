"""Simulatie: tussen twee laadkwartieren wordt niet tussendoor het huis gevoed als de voorraad voor de piek nodig is."""
from datetime import datetime, timedelta

from custom_components.virtual_battery.logic.simulation import AMS, SimBlock, SimInputs, simulate

NOW = datetime(2026, 11, 1, 13, 30, tzinfo=AMS)


def _sim(plan_idx):
    blocks = []
    for i in range(32):
        t = NOW + timedelta(minutes=15 * i)
        price = 0.418 if i < 2 else (0.411 if i < 6 else 0.514)
        blocks.append(SimBlock(key=int(t.timestamp() * 1000), end_ms=int((t + timedelta(minutes=15)).timestamp() * 1000),
                               price=price, dur_h=0.25, plan=plan_idx.get(i)))
    return simulate(SimInputs(now_ms=int(NOW.timestamp() * 1000), strategy="hybrid", feed_in_discount=0.11, max_margin=0.15,
                              soc_kwh=0.8, realised_today=0.0, cap_kwh=12.0, max_power_w=3500, wear_per_kwh=0.0067,
                              profile=None, base_load_fallback_w=800, solar_map={}, solar_factor=0.0, blocks=blocks,
                              min_soc_pct=0))


def test_soc_blijft_staan_tot_geplande_ontlading():
    O = {"action": "ontladen", "power_w": 3500}
    L = {"action": "laden", "power_w": 3500}
    res = _sim({2: L, 12: O, 13: O})
    soc = {p[0]: p[1] for p in res["soc_reeks"]}
    ts = sorted(soc)
    # tot het eerste geplande ontlaadkwartier (index 12) daalt de SoC nergens
    grens = int((NOW + timedelta(minutes=15 * 12)).timestamp() * 1000)
    waarden = [soc[t] for t in ts if t <= grens]
    assert all(b >= a - 1e-9 for a, b in zip(waarden, waarden[1:]))
