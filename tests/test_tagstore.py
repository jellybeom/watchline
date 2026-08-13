"""종목별 태그 기록과 판정 규칙 테스트."""

from __future__ import annotations

import json

import pytest

from watchline import kospi, tagstore
from watchline import watchlist as W
from watchline.tagstore import Verdict

TAG_ORDER = [
    "#KOSPI상승장",
    "#KOSPI하락횡보장",
    "#시장을이기는종목",
    "#상한가",
    "#테마주",
    "#섹터주",
]


def _csv(lines: list[str]) -> bytes:
    return ("\r\n".join(lines) + "\r\n").encode("cp949")


HEAD = "분,신,종목명,현재가,등락률,L일봉H,거래대금,메모,종목코드"


def make_wl(tmp_path, items: list[tuple[str, str]]):
    """(종목코드, 기준봉) 목록으로 관심종목 파일을 만든다."""
    lines = [HEAD]
    for code, day in items:
        if day:
            y, m, d = day.split("-")
            lines.append(f"BLANK|기준봉 {y}년 {int(m)}월 {int(d)}일,,,,,,,,")
        lines.append(f'증,,종목{code},"1",1,1 2 3 4,"1",,\'{code}')
    p = tmp_path / "w.csv"
    p.write_bytes(_csv(lines))
    return W.load(p)


@pytest.fixture
def store():
    s = tagstore.TagStore()
    s.put("900290", "2026-08-06", ["#상한가", "#테마주"])
    return s


# ────────────────────────────── 저장/읽기 ──────────────────────────────


def test_load_missing_file_is_empty(tmp_path):
    assert len(tagstore.load(tmp_path / "없음.json")) == 0


def test_save_load_roundtrip(tmp_path, store):
    p = tmp_path / "s.json"
    tagstore.save(store, p)
    again = tagstore.load(p)
    e = again.get("900290")
    assert e.date == "2026-08-06" and e.tags == ["#상한가", "#테마주"]


def test_saved_shape_matches_spec(tmp_path, store):
    p = tmp_path / "s.json"
    store.put("000660", "2026-08-13", [])
    tagstore.save(store, p)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["000660"] == {"date": "2026-08-13", "tags": []}
    assert list(raw) == ["000660", "900290"]  # 코드 순 정렬


def test_one_entry_per_code(tmp_path, store):
    """같은 종목을 다시 넣으면 덮어쓴다."""
    store.put("900290", "2026-08-12", ["#섹터주"])
    assert len(store) == 1
    assert store.get("900290").date == "2026-08-12"


def test_load_skips_invalid(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(
        json.dumps(
            {
                "900290": {"date": "2026-08-06", "tags": ["#상한가"]},
                "111111": {"date": "20260806", "tags": []},  # 날짜 형식 오류
                "222222": {"date": "2026-08-06", "tags": "문자열"},  # tags가 목록 아님
            }
        ),
        encoding="utf-8",
    )
    s = tagstore.load(p)
    assert list(s.entries) == ["900290"]
    assert len(s.skipped) == 2


def test_load_broken_json_raises(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{ 깨짐", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        tagstore.load(p)


# ────────────────────────────── 판정 ──────────────────────────────


@pytest.mark.parametrize(
    ("day", "want"),
    [
        ("2026-08-06", Verdict.SAME),
        ("2026-08-07", Verdict.NEWER),
        ("2026-08-05", Verdict.OLDER),
        ("", Verdict.NO_DATE),
    ],
)
def test_verdict_by_date(tmp_path, store, day, want):
    wl = make_wl(tmp_path, [("900290", day)])
    assert tagstore.judge(wl, store)[0].verdict is want


def test_unknown_code_is_new(tmp_path, store):
    wl = make_wl(tmp_path, [("005930", "2026-08-06")])
    assert tagstore.judge(wl, store)[0].verdict is Verdict.NEW


def test_judge_does_not_mutate(tmp_path, store):
    wl = make_wl(tmp_path, [("900290", "2026-08-05")])
    tagstore.judge(wl, store)
    assert wl.rows[0].ref_date == "2026-08-05"
    assert wl.rows[0].tags == []


# ────────────────────────────── 적용 ──────────────────────────────


def test_same_restores_stored_tags(tmp_path, store):
    wl = make_wl(tmp_path, [("900290", "2026-08-06")])
    tagstore.apply_decisions(wl, tagstore.judge(wl, store))
    assert wl.rows[0].tags == ["#상한가", "#테마주"]
    assert wl.rows[0].ref_date == "2026-08-06"


def test_newer_clears_tags_and_keeps_file_date(tmp_path, store):
    wl = make_wl(tmp_path, [("900290", "2026-08-07")])
    tagstore.apply_decisions(wl, tagstore.judge(wl, store))
    assert wl.rows[0].tags == []
    assert wl.rows[0].ref_date == "2026-08-07"


def test_new_clears_tags(tmp_path, store):
    wl = make_wl(tmp_path, [("005930", "2026-08-07")])
    tagstore.apply_decisions(wl, tagstore.judge(wl, store))
    assert wl.rows[0].tags == []


def test_no_date_clears_tags(tmp_path, store):
    wl = make_wl(tmp_path, [("111111", "")])  # 구간 행이 없어 기준봉 없음
    st = tagstore.apply_decisions(wl, tagstore.judge(wl, store))
    assert wl.rows[0].ref_date == ""
    assert wl.rows[0].tags == []
    assert st["no_date"] == 1


def test_older_keep_stored(tmp_path, store):
    wl = make_wl(tmp_path, [("900290", "2026-08-05")])
    d = tagstore.judge(wl, store)
    tagstore.apply_decisions(wl, d, {"900290": True})
    assert wl.rows[0].ref_date == "2026-08-06"  # 기록된 날짜로
    assert wl.rows[0].tags == ["#상한가", "#테마주"]


def test_older_use_file_date(tmp_path, store):
    wl = make_wl(tmp_path, [("900290", "2026-08-05")])
    d = tagstore.judge(wl, store)
    tagstore.apply_decisions(wl, d, {"900290": False})
    assert wl.rows[0].ref_date == "2026-08-05"
    assert wl.rows[0].tags == []


def test_older_defaults_to_stored(tmp_path, store):
    """선택이 없으면 안전한 쪽인 기록 유지."""
    wl = make_wl(tmp_path, [("900290", "2026-08-05")])
    st = tagstore.apply_decisions(wl, tagstore.judge(wl, store))
    assert wl.rows[0].ref_date == "2026-08-06"
    assert st["pending"] == 1


def test_market_tags_survive_apply(tmp_path, store):
    """KOSPI 태그는 기록과 별개이므로 지워지지 않는다."""
    wl = make_wl(tmp_path, [("900290", "2026-08-07")])
    wl.rows[0].tags = ["#KOSPI상승장"]
    tagstore.apply_decisions(wl, tagstore.judge(wl, store))
    assert wl.rows[0].tags == ["#KOSPI상승장"]


def test_stored_tags_never_include_market(tmp_path):
    """기록에 KOSPI 태그가 섞여 있어도 화면에 되살리지 않는다."""
    s = tagstore.TagStore()
    s.put("900290", "2026-08-06", ["#KOSPI하락횡보장", "#상한가"])
    wl = make_wl(tmp_path, [("900290", "2026-08-06")])
    tagstore.apply_decisions(wl, tagstore.judge(wl, s))
    assert wl.rows[0].tags == ["#상한가"]


# ────────────────────────────── 기록 갱신 ──────────────────────────────


def test_update_excludes_market_tags(tmp_path):
    wl = make_wl(tmp_path, [("900290", "2026-08-07")])
    wl.rows[0].tags = ["#KOSPI상승장", "#상한가", "#테마주"]
    s = tagstore.TagStore()
    tagstore.update_from(wl, s)
    assert s.get("900290").tags == ["#상한가", "#테마주"]
    assert s.get("900290").date == "2026-08-07"


def test_update_skips_rows_without_date(tmp_path):
    wl = make_wl(tmp_path, [("900290", "")])
    wl.rows[0].tags = ["#상한가"]
    s = tagstore.TagStore()
    st = tagstore.update_from(wl, s)
    assert len(s) == 0 and st["skipped_no_date"] == 1


def test_update_records_empty_tags(tmp_path):
    wl = make_wl(tmp_path, [("900290", "2026-08-07")])
    s = tagstore.TagStore()
    tagstore.update_from(wl, s)
    assert s.get("900290").tags == []


def test_update_overwrites_existing(tmp_path, store):
    wl = make_wl(tmp_path, [("900290", "2026-08-12")])
    wl.rows[0].tags = ["#섹터주"]
    tagstore.update_from(wl, store)
    assert len(store) == 1
    assert store.get("900290").date == "2026-08-12"
    assert store.get("900290").tags == ["#섹터주"]


# ────────────────────────── 전체 흐름 순서 ──────────────────────────


def test_market_tag_follows_resolved_date(tmp_path, store):
    """OLDER에서 기록 날짜를 택하면 KOSPI 태그도 그 날짜를 따라야 한다."""
    log = kospi.MarketLog()
    log.set("2026-08-05", kospi.DOWN)
    log.set("2026-08-06", kospi.UP)

    wl = make_wl(tmp_path, [("900290", "2026-08-05")])
    decisions = tagstore.judge(wl, store)
    tagstore.apply_decisions(wl, decisions, {"900290": True})
    kospi.apply_market_tags(wl, log, TAG_ORDER)

    assert wl.rows[0].ref_date == "2026-08-06"
    assert "#KOSPI상승장" in wl.rows[0].tags
    assert "#KOSPI하락횡보장" not in wl.rows[0].tags


def test_full_cycle_round_trip(tmp_path):
    """적용 → 사용자 체크 → 기록 갱신 → 다시 열기."""
    s = tagstore.TagStore()
    wl = make_wl(tmp_path, [("900290", "2026-08-07")])

    tagstore.apply_decisions(wl, tagstore.judge(wl, s))
    assert wl.rows[0].tags == []

    wl.rows[0].tags = ["#상한가"]
    tagstore.update_from(wl, s)

    wl2 = make_wl(tmp_path, [("900290", "2026-08-07")])
    tagstore.apply_decisions(wl2, tagstore.judge(wl2, s))
    assert wl2.rows[0].tags == ["#상한가"]


# ────────────────── KOSPI 태그는 사용자 편집 대상이 아님 ──────────────────


def test_market_tags_helper(tmp_path):
    from watchline.config import Settings

    cfg = Settings()
    assert tagstore.market_tags(cfg) == {"#KOSPI상승장", "#KOSPI하락횡보장"}


def test_pasted_tags_do_not_carry_market(tmp_path):
    """다른 종목의 태그를 옮겨도 KOSPI 태그는 각자 기준봉을 따른다."""
    log = kospi.MarketLog()
    log.set("2026-08-06", kospi.UP)
    log.set("2026-08-07", kospi.DOWN)

    wl = make_wl(tmp_path, [("900290", "2026-08-06"), ("005930", "2026-08-07")])
    kospi.apply_market_tags(wl, log, TAG_ORDER)
    wl.rows[0].tags = tagstore.order_tags(
        wl.rows[0].tags + ["#상한가"], tag_order=TAG_ORDER
    )

    # UI의 붙여넣기와 같은 규칙: KOSPI 태그를 뺀 것만 옮긴다.
    mkt = tagstore.market_tags()
    buffer = [t for t in wl.rows[0].tags if t not in mkt]
    keep = [t for t in wl.rows[1].tags if t in mkt]
    wl.rows[1].tags = [t for t in TAG_ORDER if t in buffer or t in keep]

    assert buffer == ["#상한가"]
    assert wl.rows[1].tags == ["#KOSPI하락횡보장", "#상한가"]
