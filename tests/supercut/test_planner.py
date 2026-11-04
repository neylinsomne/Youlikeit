from __future__ import annotations

import pytest

from apps.supercut import planner
from tests.supercut.helpers import add_asset, add_moment, seed_fear_world


@pytest.mark.unit
def test_allocate_water_filling():
    assert planner.allocate([3000, 20000, 20000], 20000) == [3000, 8500, 8500]
    assert planner.allocate([1000, 2000], 10_000) == [1000, 2000]               # sobra presupuesto
    alloc = planner.allocate([9000, 7000, 8000, 30_000], 21_000)
    assert sum(alloc) <= 21_000 and max(alloc) - min(alloc) <= 1


@pytest.mark.integration
def test_build_plan_orders_by_year_and_fits_budget(sconn):
    seed_fear_world(sconn)
    plan = planner.build_plan(sconn, "emotion:fear", max_duration_s=30)
    years = [it["work_year"] for it in plan["items"]]
    assert years == sorted(years) == [1962, 1968, 1972]
    assert plan["total_ms"] <= 30_000
    clip_ms = sum(it["out_ms"] - it["in_ms"] for it in plan["items"])
    assert clip_ms <= 30_000 - planner.END_CARD_MS
    carnival = plan["items"][0]
    assert (carnival["in_ms"], carnival["out_ms"]) == (4_000, 9_000)            # corto: entra completo
    assert all(it["in_ms"] in (4_000, 5_000, 6_000) for it in plan["items"])    # se conserva el inicio


@pytest.mark.integration
def test_build_plan_drops_lowest_score_when_budget_is_tight(sconn):
    seed_fear_world(sconn)
    plan = planner.build_plan(sconn, "emotion:fear", max_duration_s=10)        # 6 s → solo 2 tramos
    assert len(plan["items"]) == 2
    assert "Carnival of Souls" not in [it["work_title"] for it in plan["items"]]   # menor puntaje


@pytest.mark.integration
def test_max_works_limits_items(sconn):
    seed_fear_world(sconn)
    assert len(planner.build_plan(sconn, "emotion:fear", max_works=2)["items"]) == 2


@pytest.mark.integration
def test_plan_error_with_a_single_work(sconn):
    aid = add_asset(sconn, title="Only One", year=1970)
    add_moment(sconn, aid, start_ms=0, end_ms=5000)
    add_moment(sconn, aid, start_ms=9000, end_ms=15000)
    with pytest.raises(planner.PlanError):
        planner.plan_lesson(sconn, "emotion:fear")


@pytest.mark.integration
def test_invalid_spec_is_value_error(sconn):
    with pytest.raises(ValueError):
        planner.build_plan(sconn, "emotion:not_an_emotion")
    with pytest.raises(ValueError):
        planner.build_plan(sconn, "nonsense")


@pytest.mark.integration
def test_plan_lesson_title_default_and_custom(sconn):
    seed_fear_world(sconn)
    auto = planner.plan_lesson(sconn, "emotion:fear")
    assert auto["title"] == "Miedo: 3 películas, 1962–1972"
    custom = planner.plan_lesson(sconn, "emotion:fear", title="  El miedo  ", lang="en")
    assert custom["title"] == "El miedo" and custom["lang"] == "en"
    assert custom["script"]["outro"].startswith("Naming")
