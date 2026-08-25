"""hud_source: 가장 최근 작도 파일 고르기와 읽기."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from watchline import hud_source
from watchline.config import Settings

ENCODING = "cp949"


@pytest.fixture
def cfg(tmp_path: Path) -> Settings:
    return Settings(hero_user_root=tmp_path, hero_account_dir=tmp_path / "acct")


def drawing(*prices: float, tool: str = "20", start: int = 0) -> str:
    """작도 파일 내용을 만든다. 섹션 이름은 실제 포맷과 같이 code_N이다.

    영웅문은 섹션마다 다른 이름을 쓴다. 같은 이름이 겹치면 configparser가
    합쳐버리므로, 여러 번 이어붙일 때는 start로 번호를 비켜준다.
    """
    out = []
    for i, p in enumerate(prices, start=start):
        out.append(
            f"[code_{i}]\r\n차트번호=0\r\n분석도구유형={tool}\r\n"
            f"시작값={p}\r\n종료값={float(p) - 0.1}\r\n추가값=0\r\n"
        )
    return "\r\n".join(out)


def write(acct: Path, name: str, text: str, mtime: float | None = None) -> Path:
    acct.mkdir(parents=True, exist_ok=True)
    p = acct / name
    p.write_bytes(text.encode(ENCODING))
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


# ────────────────────────────── 고르기 ──────────────────────────────


def test_find_latest_picks_newest(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    write(acct, "660000_2$dr@044490_0.cs5", drawing(100), mtime=1000)
    write(acct, "660000_2$dr@005930_0.cs5", drawing(200), mtime=3000)
    write(acct, "660000_2$dr@000660_0.cs5", drawing(300), mtime=2000)

    s = hud_source.find_latest(acct, cfg)
    assert s is not None
    assert s.code == "005930"
    assert s.mtime == 3000


def test_find_latest_uppercases_code(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    write(acct, "660000_2$dr@0015n0_0.cs5", drawing(100))
    s = hud_source.find_latest(acct, cfg)
    assert s.code == "0015N0"


def test_find_latest_ignores_other_periods(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    write(acct, "660000_2$dr@044490_0.cs5", drawing(100), mtime=1000)
    write(acct, "660000_2$dr@005930_1.cs5", drawing(200), mtime=9000)  # 주봉
    s = hud_source.find_latest(acct, cfg)
    assert s.code == "044490"


def test_find_latest_ignores_layout_files(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    write(acct, "660000_2$dr@044490_0.cs5", drawing(100), mtime=1000)
    for name in ("660000_2$ls@CHART11.cs5", "ChartTool.ini", "660000_2$ls@CHART11.cs6"):
        write(acct, name, "x", mtime=9000)
    s = hud_source.find_latest(acct, cfg)
    assert s.code == "044490"


def test_find_latest_honours_screen_prefix(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    cfg = replace(cfg, screen_prefix="660000_2")
    write(acct, "660000_2$dr@044490_0.cs5", drawing(100), mtime=1000)
    write(acct, "770000_9$dr@005930_0.cs5", drawing(200), mtime=9000)
    s = hud_source.find_latest(acct, cfg)
    assert s.code == "044490"


def test_find_latest_none_when_empty(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    acct.mkdir()
    assert hud_source.find_latest(acct, cfg) is None


def test_find_latest_none_when_folder_missing(cfg: Settings, tmp_path: Path):
    assert hud_source.find_latest(tmp_path / "없는폴더", cfg) is None


def test_find_latest_skips_directories(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    write(acct, "660000_2$dr@044490_0.cs5", drawing(100), mtime=1000)
    (acct / "660000_2$dr@999999_0.cs5").mkdir()
    s = hud_source.find_latest(acct, cfg)
    assert s.code == "044490"


# ────────────────────────────── 변경 감지 ──────────────────────────────


def test_stamp_same_as_detects_no_change(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    write(acct, "660000_2$dr@044490_0.cs5", drawing(100, 95, 90), mtime=1000)
    a = hud_source.find_latest(acct, cfg)
    b = hud_source.find_latest(acct, cfg)
    assert b.same_as(a)
    assert not a.same_as(None)


def test_stamp_changes_when_content_rewritten(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    write(acct, "660000_2$dr@044490_0.cs5", drawing(100, 95, 90), mtime=1000)
    a = hud_source.find_latest(acct, cfg)
    write(acct, "660000_2$dr@044490_0.cs5", drawing(100, 95, 88), mtime=2000)
    b = hud_source.find_latest(acct, cfg)
    assert not b.same_as(a)


def test_stamp_changes_when_size_differs_at_same_mtime(cfg: Settings, tmp_path: Path):
    """시각이 같아도 크기가 다르면 다른 내용으로 본다."""
    acct = tmp_path / "acct"
    write(acct, "660000_2$dr@044490_0.cs5", drawing(100, 95, 90), mtime=1000)
    a = hud_source.find_latest(acct, cfg)
    write(acct, "660000_2$dr@044490_0.cs5", drawing(100, 95, 90, 85), mtime=1000)
    b = hud_source.find_latest(acct, cfg)
    assert not b.same_as(a)


# ────────────────────────────── 읽기 ──────────────────────────────


def test_read_returns_sorted_unique_prices(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    write(acct, "660000_2$dr@044490_0.cs5", drawing(91_600, 100_000, 96_500, 96_500))
    s = hud_source.find_latest(acct, cfg)
    r = hud_source.read(s, cfg)
    assert r.error is None
    assert r.prices == (100_000, 96_500, 91_600)


def test_read_ignores_non_horizontal_tools(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    body = drawing(100_000, 96_500, 91_600) + drawing(
        50_000, 40_000, tool="21", start=3
    )
    write(acct, "660000_2$dr@044490_0.cs5", body)
    s = hud_source.find_latest(acct, cfg)
    assert hud_source.read(s, cfg).prices == (100_000, 96_500, 91_600)


def test_read_handles_korean_text_in_file(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    body = "[memo_9]\r\n분석도구유형=30\r\n내용=상한가 자리\r\n\r\n" + drawing(
        100, 95, 90
    )
    write(acct, "660000_2$dr@044490_0.cs5", body)
    s = hud_source.find_latest(acct, cfg)
    assert hud_source.read(s, cfg).prices == (100, 95, 90)


def test_read_empty_file_is_not_an_error(cfg: Settings, tmp_path: Path):
    """선을 하나도 안 그은 종목은 오류가 아니라 '선 부족'이다."""
    acct = tmp_path / "acct"
    write(acct, "660000_2$dr@044490_0.cs5", "")
    s = hud_source.find_latest(acct, cfg)
    r = hud_source.read(s, cfg)
    assert r.prices == ()
    assert r.error is None


def test_read_reports_broken_content(cfg: Settings, tmp_path: Path):
    """쓰는 도중에 잡힌 반쪽짜리 파일은 오류로 알린다."""
    acct = tmp_path / "acct"
    write(
        acct, "660000_2$dr@044490_0.cs5", "[code_0]\r\n분석도구유형=20\r\n시작값=\r\n"
    )
    s = hud_source.find_latest(acct, cfg)
    r = hud_source.read(s, cfg)
    assert r.prices == ()
    assert r.error and "빈 값" in r.error


def test_read_floors_decimal_prices(cfg: Settings, tmp_path: Path):
    acct = tmp_path / "acct"
    write(acct, "660000_2$dr@044490_0.cs5", drawing(1050.7, 1010.2, 970.9))
    s = hud_source.find_latest(acct, cfg)
    assert hud_source.read(s, cfg).prices == (1050, 1010, 970)
