"""hud_model 계산 규칙 검증.

창을 띄우지 않고 확인할 수 있는 것은 모두 여기서 확인한다.
"""

from __future__ import annotations

import pytest

from watchline import hud_model as m

STEPS = m.FLOOR_STEPS
GUIDES = m.GUIDES


# ────────────────────────────── 기본 ──────────────────────────────


def test_pct_of():
    assert m.pct_of(100_000, 93_000) == pytest.approx(-7.0)
    assert m.pct_of(100_000, 100_000) == 0.0
    assert m.pct_of(0, 100) == 0.0  # 0으로 나누지 않는다


def test_guide_price_rounds_to_won():
    assert m.guide_price(100_000, -7.0) == 93_000
    assert m.guide_price(99_999, -7.0) == 92_999


def test_top_prices_dedups_and_sorts():
    assert m.top_prices([90, 100, 95, 95, 80]) == (100, 95, 90)
    assert m.top_prices([100.9, 100.1]) == (100,)  # 정수로 통일


# ────────────────────────────── 배율 계단 ──────────────────────────────


@pytest.mark.parametrize(
    "low,expected",
    [
        (-0.5, -10.0),
        (-8.4, -10.0),
        (-9.99, -10.0),
        (-10.0, -10.0),  # 경계는 그 계단에 포함된다
        (-10.01, -15.0),
        (-15.0, -15.0),
        (-15.1, -20.0),
        (-20.0, -20.0),
        (-24.9, -25.0),
        (-25.0, -25.0),
    ],
)
def test_choose_floor_steps(low, expected):
    floor, clamped = m.choose_floor(low, STEPS)
    assert floor == expected
    assert clamped is False


def test_choose_floor_clamps_past_last_step():
    floor, clamped = m.choose_floor(-31.2, STEPS)
    assert floor == -25.0
    assert clamped is True


def test_choose_floor_rejects_empty_steps():
    with pytest.raises(ValueError):
        m.choose_floor(-5.0, ())


# ────────────────────────────── 뷰 구성 ──────────────────────────────


def test_build_view_normal():
    v = m.build_view("067290", [100_000, 96_500, 91_600])
    assert v.ok
    assert v.prices == (100_000, 96_500, 91_600)
    assert v.spread == pytest.approx(-8.4)
    assert v.floor == -10.0
    assert v.clamped is False


def test_build_view_takes_top_three_only():
    v = m.build_view("A", [100_000, 96_500, 91_600, 80_000, 70_000])
    assert v.prices == (100_000, 96_500, 91_600)


def test_build_view_dedups_before_counting():
    # 중복을 세면 3개로 보이지만 실제로는 2개뿐이다.
    v = m.build_view("A", [100_000, 96_500, 96_500])
    assert not v.ok
    assert "2개" in v.warning
    assert v.found == (100_000, 96_500)


@pytest.mark.parametrize("prices", [[], [100_000], [100_000, 90_000]])
def test_build_view_warns_when_lines_missing(prices):
    v = m.build_view("A", prices)
    assert not v.ok
    assert v.marks == ()
    assert v.spread is None
    assert v.found == tuple(sorted(prices, reverse=True))


def test_build_view_title_falls_back_to_code():
    assert m.build_view("067290", [3, 2, 1]).title == "067290"
    assert m.build_view("067290", [3, 2, 1], name="에스티팜").title == "에스티팜"


def test_gaps():
    v = m.build_view("A", [100_000, 96_500, 91_600])
    g1, g2 = v.gaps()
    assert g1 == pytest.approx(-3.5)
    assert g2 == pytest.approx(-5.0777, abs=1e-3)


def test_breached():
    v = m.build_view("A", [100_000, 96_500, 91_600])  # -8.4%
    assert v.breached(-7.0)
    assert not v.breached(-10.0)


# ────────────────────────────── 가이드선 병합 ──────────────────────────────


def marks_of(prices, guides=GUIDES):
    return m.build_view("A", prices, guides=guides).marks


def test_marks_ordered_top_to_bottom():
    ms = marks_of([100_000, 96_500, 91_600])
    pcts = [x.pct for x in ms]
    assert pcts == sorted(pcts, reverse=True)
    assert [x.label for x in ms] == ["1선", "2선", "-7%", "3선", "-10%"]


def test_guide_merges_when_price_matches_exactly():
    # 1선 100,000 → -7%는 정확히 93,000. 3선이 여기 걸린다.
    ms = marks_of([100_000, 96_500, 93_000])
    labels = [x.label for x in ms]
    assert "3선 = -7%" in labels
    assert "-7%" not in labels  # 따로 그리지 않는다
    assert sum(1 for x in ms if x.price == 93_000) == 1
    merged = next(x for x in ms if x.merged)
    assert merged.kind == m.KIND_LINE  # 실선 스타일로 그린다


def test_guide_merges_on_ten_percent_too():
    ms = marks_of([100_000, 96_500, 90_000])
    labels = [x.label for x in ms]
    assert "3선 = -10%" in labels
    assert "-10%" not in labels


def test_guide_merge_survives_float_noise():
    # 99,999의 -7%는 92,999.07. 원 단위로는 92,999와 같다.
    ms = marks_of([99_999, 96_000, 92_999])
    assert any(x.merged for x in ms)


def test_near_miss_does_not_merge():
    ms = marks_of([100_000, 96_500, 92_990])  # -7%는 93,000
    assert not any(x.merged for x in ms)
    assert "-7%" in [x.label for x in ms]


def test_two_lines_can_merge_with_two_guides():
    ms = marks_of([100_000, 93_000, 90_000])
    labels = [x.label for x in ms]
    assert labels == ["1선", "2선 = -7%", "3선 = -10%"]
    assert len(ms) == 3


def test_guide_outside_floor_is_dropped():
    ms = m.build_marks((100_000, 96_000, 92_000), guides=(-7.0, -20.0), floor=-10.0)
    assert "-20%" not in [x.label for x in ms]
    assert "-7%" in [x.label for x in ms]


def test_marks_empty_for_no_prices():
    assert m.build_marks(()) == ()


# ────────────────────────────── 좌표 ──────────────────────────────


def test_y_of_endpoints():
    assert m.y_of(0.0, -10.0, 200) == 0.0
    assert m.y_of(-10.0, -10.0, 200) == 200.0
    assert m.y_of(-5.0, -10.0, 200) == 100.0


def test_y_of_clamps_out_of_range():
    assert m.y_of(-30.0, -25.0, 200) == 200.0  # 아래로 넘쳐도 바닥에 붙는다
    assert m.y_of(5.0, -10.0, 200) == 0.0
    assert m.y_of(-5.0, 0.0, 200) == 0.0  # 0으로 나누지 않는다


# ────────────────────────────── 라벨 간격 ──────────────────────────────


def test_nudge_leaves_roomy_labels_alone():
    ys = [0.0, 60.0, 120.0]
    assert m.nudge(ys, 18, 0, 200) == ys


def test_nudge_separates_crowded_labels():
    out = m.nudge([100.0, 104.0, 108.0], 18, 0, 300)
    assert all(b - a >= 18 - 1e-9 for a, b in zip(out, out[1:], strict=False))


def test_nudge_keeps_input_order():
    # 입력 순서가 y 순서와 다를 때도 자리를 바꾸지 않는다.
    out = m.nudge([100.0, 20.0, 105.0], 18, 0, 300)
    assert out[1] < out[0] < out[2]


def test_nudge_respects_bounds():
    out = m.nudge([0.0, 2.0, 4.0, 6.0], 18, 0, 100)
    assert min(out) >= -1e-9
    assert max(out) <= 100 + 1e-9


def test_nudge_pushes_back_from_bottom():
    out = m.nudge([95.0, 97.0, 99.0], 18, 0, 100)
    assert max(out) <= 100 + 1e-9
    assert all(b - a >= 18 - 1e-9 for a, b in zip(out, out[1:], strict=False))


def test_nudge_distributes_evenly_when_space_is_short():
    out = m.nudge([10.0, 11.0, 12.0, 13.0], 18, 0, 30)
    assert out == pytest.approx([0.0, 10.0, 20.0, 30.0])


@pytest.mark.parametrize("ys", [[], [42.0]])
def test_nudge_trivial_cases(ys):
    assert m.nudge(ys, 18, 0, 100) == ys


def test_label_ys_matches_mark_count():
    v = m.build_view("A", [100_000, 96_500, 91_600])
    lines, labels = m.label_ys(v.marks, v.floor, 236, 18)
    assert len(lines) == len(labels) == len(v.marks)
    assert lines[0] == 0.0  # 1선은 맨 위


def test_label_ys_never_moves_the_lines():
    # 라벨이 밀려도 선의 위치는 그대로여야 한다.
    v = m.build_view("A", [100_000, 99_700, 99_400])
    lines, labels = m.label_ys(v.marks, v.floor, 236, 18)
    expected = [m.y_of(x.pct, v.floor, 236) for x in v.marks]
    assert lines == expected
    assert labels != expected  # 붙어 있었으므로 라벨은 밀렸다


# ────────────────────────── 극단값 통합 확인 ──────────────────────────


def test_deep_spread_widens_scale_and_keeps_guides():
    v = m.build_view("A", [100_000, 95_000, 82_000])  # -18%
    assert v.floor == -20.0
    labels = [x.label for x in v.marks]
    assert labels == ["1선", "2선", "-7%", "-10%", "3선"]
    assert not v.clamped


def test_beyond_last_step_is_clamped_but_still_drawable():
    v = m.build_view("A", [100_000, 95_000, 60_000])  # -40%
    assert v.floor == -25.0
    assert v.clamped
    lines, _ = m.label_ys(v.marks, v.floor, 236, 18)
    assert max(lines) == 236  # 바닥에 붙는다


def test_penny_stock_prices_stay_integral():
    v = m.build_view("A", [1_050, 1_010, 970])
    assert all(isinstance(x.price, int) for x in v.marks)
    assert v.spread == pytest.approx(-7.619, abs=1e-3)
