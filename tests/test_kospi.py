"""KOSPI 장 기록과 태그 자동 적용 테스트."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from watchline import kospi
from watchline import watchlist as W

TAG_ORDER = [
    "#KOSPI상승장",
    "#KOSPI하락횡보장",
    "#시장을이기는종목",
    "#상한가",
    "#테마주",
    "#섹터주",
]


# ────────────────────────── 저장/읽기 ──────────────────────────


def test_load_missing_file_is_empty(tmp_path):
    log = kospi.load(tmp_path / "없음.json")
    assert len(log) == 0
    assert log.skipped == []


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "kospi.json"
    log = kospi.MarketLog()
    log.set("2026-08-07", kospi.DOWN)
    log.set("2026-08-06", kospi.UP)
    kospi.save(log, p)

    again = kospi.load(p)
    assert again.states == {"2026-08-06": "up", "2026-08-07": "down"}


def test_saved_file_is_sorted_and_readable(tmp_path):
    """git diff가 깔끔하도록 날짜 순으로 저장한다."""
    p = tmp_path / "kospi.json"
    log = kospi.MarketLog()
    for day in ("2026-08-07", "2026-08-05", "2026-08-06"):
        log.set(day, kospi.UP)
    kospi.save(log, p)

    text = p.read_text(encoding="utf-8")
    assert list(json.loads(text)) == ["2026-08-05", "2026-08-06", "2026-08-07"]
    assert "\n" in text  # 사람이 읽을 수 있게 들여쓰기


def test_load_skips_invalid_entries(tmp_path):
    p = tmp_path / "kospi.json"
    p.write_text(
        json.dumps(
            {
                "2026-08-07": "up",
                "2026-13-01": "up",  # 없는 달
                "20260807": "up",  # 형식 오류
                "2026-08-08": "sideways",  # 없는 상태
            }
        ),
        encoding="utf-8",
    )

    log = kospi.load(p)
    assert log.states == {"2026-08-07": "up"}
    assert len(log.skipped) == 3


def test_load_broken_json_raises(tmp_path):
    p = tmp_path / "kospi.json"
    p.write_text("{ 깨진 파일", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        kospi.load(p)


def test_set_rejects_bad_input():
    log = kospi.MarketLog()
    with pytest.raises(ValueError, match="날짜"):
        log.set("2026/08/07", kospi.UP)
    with pytest.raises(ValueError, match="상태"):
        log.set("2026-08-07", "boom")


def test_remove():
    log = kospi.MarketLog()
    log.set("2026-08-07", kospi.UP)
    assert log.remove("2026-08-07") is True
    assert log.remove("2026-08-07") is False


def test_market_closed(monkeypatch):
    from watchline import config

    cfg = config.settings
    assert kospi.market_closed(datetime(2026, 8, 7, 20, 0), cfg) is True
    assert kospi.market_closed(datetime(2026, 8, 7, 19, 59), cfg) is False


# ────────────────────────── 태그 적용 ──────────────────────────


@pytest.fixture
def log():
    m = kospi.MarketLog()
    m.set("2026-08-06", kospi.UP)
    m.set("2026-08-07", kospi.DOWN)
    return m


def test_applies_tag_by_ref_date(sample_input, log):
    wl = W.load(sample_input)
    wl.rows[0].ref_date = "2026-08-06"
    wl.rows[1].ref_date = "2026-08-07"

    stat = kospi.apply_market_tags(wl, log, TAG_ORDER)

    assert wl.rows[0].tags == ["#KOSPI상승장"]
    assert wl.rows[1].tags == ["#KOSPI하락횡보장"]
    assert stat["up"] == 1 and stat["down"] == 1


def test_no_date_and_no_record_counted(sample_input, log):
    wl = W.load(sample_input)
    wl.rows[0].ref_date = ""
    wl.rows[1].ref_date = "2020-01-01"  # 기록에 없는 날
    wl.rows[2].ref_date = "2026-08-06"

    stat = kospi.apply_market_tags(wl, log, TAG_ORDER)
    assert stat["no_date"] == 1
    assert stat["no_record"] == 1
    assert stat["up"] == 1


def test_other_tags_are_preserved(sample_input, log):
    wl = W.load(sample_input)
    wl.rows[0].ref_date = "2026-08-06"
    wl.rows[0].tags = ["#상한가", "#테마주"]

    kospi.apply_market_tags(wl, log, TAG_ORDER)
    assert wl.rows[0].tags == ["#KOSPI상승장", "#상한가", "#테마주"]


def test_wrong_tag_is_corrected(sample_input, log):
    """기록을 고친 뒤 다시 적용하면 잘못 붙은 태그가 교정된다."""
    wl = W.load(sample_input)
    wl.rows[0].ref_date = "2026-08-07"
    wl.rows[0].tags = ["#KOSPI상승장", "#상한가"]  # 오인 입력 상태

    kospi.apply_market_tags(wl, log, TAG_ORDER)
    assert wl.rows[0].tags == ["#KOSPI하락횡보장", "#상한가"]


def test_tag_removed_when_date_cleared(sample_input, log):
    wl = W.load(sample_input)
    wl.rows[0].ref_date = "2026-08-06"
    kospi.apply_market_tags(wl, log, TAG_ORDER)
    assert wl.rows[0].tags == ["#KOSPI상승장"]

    wl.rows[0].ref_date = ""
    stat = kospi.apply_market_tags(wl, log, TAG_ORDER)
    assert wl.rows[0].tags == []
    assert stat["cleared"] == 1


def test_apply_is_idempotent(sample_input, log):
    wl = W.load(sample_input)
    wl.rows[0].ref_date = "2026-08-06"
    kospi.apply_market_tags(wl, log, TAG_ORDER)
    first = list(wl.rows[0].tags)
    kospi.apply_market_tags(wl, log, TAG_ORDER)
    assert wl.rows[0].tags == first


def test_prices_and_base_untouched(sample_input, log):
    wl = W.load(sample_input)
    W.apply_lines(wl, {"900290": (1, 2, 3)})
    for r in wl.rows:
        r.ref_date = "2026-08-06"
    base = [dict(r.base) for r in wl.rows]
    lines = [list(r.lines) for r in wl.rows]

    kospi.apply_market_tags(wl, log, TAG_ORDER)
    assert [dict(r.base) for r in wl.rows] == base
    assert [list(r.lines) for r in wl.rows] == lines
