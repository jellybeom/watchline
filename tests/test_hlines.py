"""수평선 추출 테스트."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from watchline import hlines
from watchline.config import Settings


def make_cfg(root: Path, **over) -> Settings:
    base = Settings(
        hero_user_root=root,
        hero_account_dir=None,
        screen_prefix=None,
        hline_type="20",
        period_index="0",
        top_n=3,
        spread_limit=0.10,
        price_tolerance=0.01,
        stale_days=30,
        tags_file=root / "tags.txt",
        default_csv=None,
    )
    return dataclasses.replace(base, **over)


def write_drawing(
    acct: Path, code: str, prices, *, period="0", screen="660000_2", tool="20"
) -> Path:
    """작도 파일 하나를 만든다(실제 포맷과 동일한 CP949 INI)."""
    secs = []
    for i, p in enumerate(prices):
        secs.append(
            f"[code_{i}]\r\n"
            f"차트번호=0\r\n분석도구유형={tool}\r\n라인색상=16711935\r\n"
            f"라인너비=3\r\nlfFaceName=맑은 고딕\r\n글상자배경색=255|255|255\r\n"
            f"시작일자=20260721\r\n종료일자=20260721\r\n"
            f"시작값={p}\r\n종료값={float(p) - 0.1}\r\n추가값=47135.9\r\n"
        )
    path = acct / f"{screen}$dr@{code}_{period}.cs5"
    path.write_bytes("\r\n".join(secs).encode("cp949"))
    return path


@pytest.fixture
def acct(tmp_path: Path) -> Path:
    d = tmp_path / "user" / "#TEST$"
    d.mkdir(parents=True)
    return d


# ────────────────────────── 정상 경로 ──────────────────────────


def test_extracts_top_three_descending(acct):
    write_drawing(acct, "025900", [6100, 6320, 5900])  # 순서 뒤섞어 저장
    res = hlines.extract(make_cfg(acct.parent))
    assert res.lines["025900"] == (6320.0, 6100.0, 5900.0)
    assert res.spreads["025900"] == pytest.approx((6320 - 5900) / 6320)


def test_takes_highest_three_of_many(acct):
    write_drawing(acct, "900290", [3355, 3215, 3105, 3000, 2900])
    res = hlines.extract(make_cfg(acct.parent))
    assert res.lines["900290"] == (3355.0, 3215.0, 3105.0)
    assert any("하위 2개 제외" in n for n in res.notes)


def test_deduplicates_equal_prices(acct):
    write_drawing(acct, "035720", [50000, 50000, 49000, 48000])
    res = hlines.extract(make_cfg(acct.parent))
    assert res.lines["035720"] == (50000.0, 49000.0, 48000.0)
    assert any("동일 가격" in n for n in res.notes)


# ─────────────────────────── 제외 규칙 ───────────────────────────


def test_wide_spread_passes_but_is_flagged(acct):
    """낙폭이 커도 제외하지 않고, 화면에서 고칠 수 있도록 통과시킨다."""
    write_drawing(acct, "010950", [200000, 127600, 123700])
    res = hlines.extract(make_cfg(acct.parent))
    assert res.lines["010950"] == (200000.0, 127600.0, 123700.0)
    assert "010950" not in res.excluded
    assert any("가격분포" in n for n in res.notes)


def test_spread_just_under_limit_not_flagged(acct):
    write_drawing(acct, "111111", [10000, 9500, 9050])  # 9.5%
    res = hlines.extract(make_cfg(acct.parent))
    assert "111111" in res.lines
    assert not any("가격분포" in n for n in res.notes)


def test_excludes_too_few_lines(acct):
    write_drawing(acct, "005930", [70000, 69000])
    res = hlines.extract(make_cfg(acct.parent))
    assert "005930" not in res.lines
    assert "2개뿐" in res.excluded["005930"]


def test_excludes_when_multiple_screens(acct):
    write_drawing(acct, "005380", [10000, 9800, 9600], screen="660000_2")
    write_drawing(acct, "005380", [11000, 10800, 10600], screen="660000_3")
    res = hlines.extract(make_cfg(acct.parent))
    assert "005380" not in res.lines
    assert "여러 화면" in res.excluded["005380"]


# ─────────────────────────── 필터링 ───────────────────────────


def test_ignores_other_periods(acct):
    write_drawing(acct, "068270", [10000, 9800, 9600], period="1")
    write_drawing(acct, "025900", [6320, 6100, 5900], period="0")
    res = hlines.extract(make_cfg(acct.parent))
    assert set(res.lines) == {"025900"}
    assert res.periods == {"0": 1, "1": 1}


def test_ignores_other_tool_types(acct):
    write_drawing(acct, "025900", [6320, 6100, 5900], tool="21")
    res = hlines.extract(make_cfg(acct.parent))
    assert "025900" in res.excluded
    assert res.types["21"] == 3


def test_alphanumeric_code_is_accepted(acct):
    write_drawing(acct, "Q50001", [1000, 980, 960])
    res = hlines.extract(make_cfg(acct.parent))
    assert "Q50001" in res.lines


def test_screen_prefix_filter(acct):
    write_drawing(acct, "005380", [10000, 9800, 9600], screen="660000_2")
    write_drawing(acct, "005930", [11000, 10800, 10600], screen="660000_3")
    res = hlines.extract(make_cfg(acct.parent, screen_prefix="660000_2"))
    assert set(res.lines) == {"005380"}


# ─────────────────────────── 오류 처리 ───────────────────────────


def test_missing_root_reports_error(tmp_path):
    res = hlines.extract(make_cfg(tmp_path / "없음"))
    assert res.error and "user 폴더" in res.error


def test_multiple_account_dirs_reports_error(tmp_path):
    root = tmp_path / "user"
    (root / "#A$").mkdir(parents=True)
    (root / "#B$").mkdir(parents=True)
    res = hlines.extract(make_cfg(root))
    assert res.error and "여러 개" in res.error


def test_corrupt_file_does_not_break_others(acct):
    write_drawing(acct, "025900", [6320, 6100, 5900])
    (acct / "660000_2$dr@999999_0.cs5").write_bytes(b"\x00\xff not an ini \x00")
    res = hlines.extract(make_cfg(acct.parent))
    assert "025900" in res.lines
    assert "999999" in res.excluded


def test_ignores_non_drawing_files(acct):
    write_drawing(acct, "025900", [6320, 6100, 5900])
    (acct / "660000_2$ls@CHART11.cs5").write_bytes(b"layout")
    (acct / "ChartTool.ini").write_bytes(b"x=1")
    res = hlines.extract(make_cfg(acct.parent))
    assert res.total == 1


def test_zero_and_negative_prices_skipped(acct):
    write_drawing(acct, "025900", [6320, 0, 6100, -100, 5900])
    res = hlines.extract(make_cfg(acct.parent))
    assert res.lines["025900"] == (6320.0, 6100.0, 5900.0)


# ─────────────────────────── 가격 내림 ───────────────────────────


def test_non_integer_price_is_floored(acct):
    write_drawing(acct, "025900", [6320.9, 6100.4, 5900.5])
    res = hlines.extract(make_cfg(acct.parent))
    assert res.lines["025900"] == (6320.0, 6100.0, 5900.0)
    assert sum("소수점 내림" in n for n in res.notes) == 3


def test_integer_price_has_no_note(acct):
    write_drawing(acct, "025900", [6320, 6100, 5900])
    res = hlines.extract(make_cfg(acct.parent))
    assert not any("소수점" in n for n in res.notes)


def test_floor_can_create_duplicates(acct):
    """내림 후 값이 겹치면 중복으로 합쳐진다."""
    write_drawing(acct, "025900", [6320.9, 6320.1, 6100, 5900])
    res = hlines.extract(make_cfg(acct.parent))
    assert res.lines["025900"] == (6320.0, 6100.0, 5900.0)
