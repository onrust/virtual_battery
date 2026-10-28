"""Eigen-verbruik-deel van een geplande ontlading volgt de echte afname van het huis."""
from datetime import datetime, timedelta

from custom_components.virtual_battery.logic.engine import AMS, Block, Inputs, State, engine_tick

NOW = datetime(2026, 11, 3, 19, 0, tzinfo=AMS)
NOW_MS = int(NOW.timestamp() * 1000)


def _inputs(plan, grid_import_w):
    blocks = [Block(key=int((NOW + timedelta(minutes=15 * i)).timestamp() * 1000),
                    start_iso=(NOW + timedelta(minutes=15 * i)).isoformat(),
                    price=0.30 if i < 8 else 0.15, dur_h=0.25) for i in range(24)]
    return Inputs(now_ms=NOW_MS, strategy="hybrid", price=0.30, feed_in_discount=0.11,
                  grid_import_w=grid_import_w, grid_export_w=0.0, cap_kwh=10.0, max_kw=3.5,
                  ha_soc=9.0, base_load_fallback_w=800, blocks=blocks,
                  schedule={NOW_MS: plan})


def _power(plan, grid_import_w):
    return engine_tick(_inputs(plan, grid_import_w), State())["power_w"]


def test_eigen_verbruik_volgt_lagere_afname():
    # gepland 834 W (alles eigen verbruik), huis neemt maar 539 W af
    assert _power({"action": "ontladen", "power_w": 834, "self_w": 834}, 539) == -539


def test_geen_afname_geen_ontlading_voor_eigen_deel():
    assert _power({"action": "ontladen", "power_w": 834, "self_w": 834}, 0) == 0


def test_hogere_afname_wordt_ook_gedekt():
    # afname boven het plan: de batterij dekt het hele huis
    assert _power({"action": "ontladen", "power_w": 834, "self_w": 834}, 1200) == -1200


def test_afname_begrensd_door_max_vermogen():
    assert _power({"action": "ontladen", "power_w": 834, "self_w": 834}, 5000) == -3500


def test_pure_verkoop_blijft_op_plan():
    # geen eigen verbruik gepland (self_w = 0): niets verandert
    assert _power({"action": "ontladen", "power_w": 3500, "self_w": 0}, 500) == -3500


def test_verkoopdeel_blijft_staan():
    # 3500 W gepland waarvan 800 W eigen verbruik; afname 500 W -> 500 + 2700
    assert _power({"action": "ontladen", "power_w": 3500, "self_w": 800}, 500) == -3200


def test_zonder_self_w_oud_gedrag():
    assert _power({"action": "ontladen", "power_w": 834}, 539) == -834
