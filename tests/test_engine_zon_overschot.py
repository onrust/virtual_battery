"""In een kwartier met 'laden' is het geplande vermogen een minimum: extra zonoverschot gaat ook de batterij in."""
from datetime import datetime, timedelta

from custom_components.virtual_battery.logic.engine import AMS, Block, Inputs, State, engine_tick

NOW = datetime(2026, 10, 31, 11, 45, tzinfo=AMS)
NOW_MS = int(NOW.timestamp() * 1000)


def _run(plan, export_w, strategy="hybrid", discount=0.11, later_price=0.50):
    blocks = [Block(key=int((NOW + timedelta(minutes=15 * i)).timestamp() * 1000),
                    start_iso=(NOW + timedelta(minutes=15 * i)).isoformat(),
                    price=0.40 if i < 8 else later_price, dur_h=0.25) for i in range(32)]
    inp = Inputs(now_ms=NOW_MS, strategy=strategy, price=0.40, feed_in_discount=discount,
                 grid_import_w=0.0, grid_export_w=export_w, cap_kwh=10.0, max_kw=3.5,
                 ha_soc=1.0, base_load_fallback_w=800, blocks=blocks,
                 schedule={NOW_MS: plan} if plan else {})
    return engine_tick(inp, State())


def test_extra_zonoverschot_boven_plan_wordt_opgeslagen():
    # plan 16 W, maar er wordt 400 W teruggeleverd en later is de stroom duurder: alles de batterij in
    assert _run({"action": "laden", "power_w": 16}, 400)["power_w"] == 400


def test_overschot_begrensd_door_max_vermogen():
    assert _run({"action": "laden", "power_w": 16}, 6000)["power_w"] == 3500


def test_hoger_plan_blijft_staan():
    # netladen volgens plan (2000 W) is meer dan het overschot: ongewijzigd
    assert _run({"action": "laden", "power_w": 2000}, 400)["power_w"] == 2000


def test_zonder_overschot_blijft_plan():
    assert _run({"action": "laden", "power_w": 16}, 0)["power_w"] == 16


def test_prijsoptimalisatie_ongewijzigd():
    assert _run({"action": "laden", "power_w": 16}, 400, strategy="price_optimization")["power_w"] == 16


def test_niet_rendabel_blijft_plan():
    # zonder terugleverkorting en zonder prijsverschil loont opslaan niet
    assert _run({"action": "laden", "power_w": 16}, 400, discount=0.0, later_price=0.40)["power_w"] == 16
