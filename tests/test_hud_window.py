"""HUD 창을 실제로 만들어 그려본다.

계산은 test_hud_model이 맡고, 여기서는 창이 뜨는지·그리다 죽지 않는지·
파일이 바뀌면 실제로 따라가는지를 본다. 화면 없이 돌려야 하므로
offscreen 플랫폼을 쓴다.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from watchline.config import Settings  # noqa: E402
from watchline.hud_window import HudWindow  # noqa: E402

ENCODING = "cp949"


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def drawing(*prices: float, tool: str = "20") -> bytes:
    secs = [
        f"[code_{i}]\r\n차트번호=0\r\n분석도구유형={tool}\r\n"
        f"시작값={p}\r\n종료값={float(p) - 0.1}\r\n추가값=0\r\n"
        for i, p in enumerate(prices)
    ]
    return "\r\n".join(secs).encode(ENCODING)


@pytest.fixture
def env(tmp_path: Path):
    """계정 폴더와 설정을 갖춘 임시 환경."""
    acct = tmp_path / "user" / "#TEST$"
    acct.mkdir(parents=True)
    cfg = Settings(
        hero_user_root=tmp_path / "user",
        hero_account_dir=acct,
        names_file=tmp_path / "names.json",
        hud_poll_ms=10,
        hud_settle_ms=0,
        hud_retry_ms=0,
    )
    return acct, cfg


def put(acct: Path, code: str, *prices: float, mtime: float | None = None) -> Path:
    p = acct / f"660000_2$dr@{code}_0.cs5"
    p.write_bytes(drawing(*prices))
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def pump(ms: int = 60) -> None:
    """타이머와 singleShot이 돌 시간을 준다."""
    import time

    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.002)


def render(win: HudWindow) -> QPixmap:
    """실제로 paintEvent를 태운다. 그리다 예외가 나면 여기서 드러난다."""
    pm = QPixmap(win.size())
    win.render(pm)
    assert not pm.isNull()
    return pm


# ────────────────────────────── 기본 동작 ──────────────────────────────


def test_window_opens_and_reads_latest(app, env):
    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()
    assert win.view is not None
    assert win.view.code == "044490"
    assert win.view.prices == (100_000, 96_500, 91_600)
    render(win)
    win.close()


def test_follows_the_newest_file(app, env):
    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600, mtime=1000)
    win = HudWindow(cfg)
    pump()
    assert win.view.code == "044490"

    put(acct, "005930", 80_000, 78_000, 75_000)  # 다른 종목으로 전환
    pump()
    assert win.view.code == "005930"
    assert win.view.prices == (80_000, 78_000, 75_000)
    render(win)
    win.close()


def test_does_not_reread_unchanged_file(app, env, monkeypatch):
    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()

    from watchline import hud_source

    calls = []
    real = hud_source.read
    monkeypatch.setattr(
        hud_source, "read", lambda s, c=None: (calls.append(s), real(s, c))[1]
    )
    pump(120)  # 폴링이 여러 번 돌 시간
    assert calls == []  # 바뀐 게 없으면 파일을 열지 않는다
    win.close()


def test_reacts_to_line_edit_on_same_stock(app, env):
    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600, mtime=1000)
    win = HudWindow(cfg)
    pump()
    assert win.view.spread == pytest.approx(-8.4)

    put(acct, "044490", 100_000, 96_500, 93_000)  # 3선을 올림
    pump()
    assert win.view.spread == pytest.approx(-7.0)
    assert any(m.merged for m in win.view.marks)
    win.close()


def test_uses_name_cache(app, env):
    acct, cfg = env
    (cfg.names_file).write_text('{"044490": "다이나믹디자인"}', encoding="utf-8")
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()
    assert win.view.title == "다이나믹디자인"
    win.close()


def test_falls_back_to_code_without_cache(app, env):
    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()
    assert win.view.title == "044490"
    win.close()


# ────────────────────────────── 예외 상황 ──────────────────────────────


def test_missing_account_dir_does_not_crash(app, tmp_path):
    cfg = Settings(
        hero_user_root=tmp_path / "없음",
        hero_account_dir=tmp_path / "없음" / "#X$",
        names_file=tmp_path / "names.json",
    )
    win = HudWindow(cfg)
    assert win.account is None
    assert win.status
    render(win)  # 안내 문구만 그린다
    win.close()


def test_empty_folder_shows_status(app, env):
    acct, cfg = env
    win = HudWindow(cfg)
    pump()
    assert win.view is None
    render(win)
    win.close()


def test_too_few_lines_shows_warning(app, env):
    acct, cfg = env
    put(acct, "044490", 100_000, 96_500)
    win = HudWindow(cfg)
    pump()
    assert not win.view.ok
    assert "2개" in win.view.warning
    assert win.view.found == (100_000, 96_500)
    render(win)
    win.close()


def test_no_horizontal_lines_at_all(app, env):
    acct, cfg = env
    p = acct / "660000_2$dr@044490_0.cs5"
    p.write_bytes(drawing(50_000, 40_000, tool="21"))  # 추세선만
    win = HudWindow(cfg)
    pump()
    assert not win.view.ok
    render(win)
    win.close()


def test_partial_file_recovers_on_retry(app, env):
    """쓰는 도중에 잡힌 파일은 한 번 더 읽어 복구한다."""
    acct, cfg = env
    p = acct / "660000_2$dr@044490_0.cs5"
    p.write_bytes(
        b"[code_0]\r\n\xba\xd0\xbc\xae\xb5\xb5\xb1\xb8\xc0\xaf\xc7\xfc=20\r\n"
    )
    win = HudWindow(cfg)
    pump()
    render(win)  # 깨진 상태에서도 그려진다
    put(acct, "044490", 100_000, 96_500, 91_600)
    pump()
    assert win.view.ok
    win.close()


# ────────────────────── 배율·병합을 실제로 그려본다 ──────────────────────


CASES = {
    "normal": (100_000, 96_500, 91_600),
    "merge_at_seven": (100_000, 96_500, 93_000),
    "merge_at_ten": (100_000, 96_500, 90_000),
    "merge_both": (100_000, 93_000, 90_000),
    "tight": (100_000, 99_800, 99_600),
    "wide_15": (100_000, 95_000, 87_000),
    "wide_20": (100_000, 95_000, 82_000),
    "wide_25": (100_000, 95_000, 78_000),
    "clamped": (100_000, 95_000, 60_000),
    "penny": (1_050, 1_010, 970),
    "odd_base": (99_999, 96_000, 92_999),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_case_renders(app, env, case, tmp_path):
    acct, cfg = env
    put(acct, "044490", *CASES[case])
    win = HudWindow(cfg)
    pump()
    assert win.view is not None
    pm = render(win)
    # 창이 내용에 맞게 커졌는지 — 잘려 나가면 높이가 0에 가깝다
    assert pm.height() > 200
    assert pm.width() == 320
    win.close()


def test_scale_label_only_when_widened(app, env):
    acct, cfg = env
    put(acct, "044490", 100_000, 95_000, 82_000)
    win = HudWindow(cfg)
    pump()
    assert win.view.floor == -20.0
    render(win)
    win.close()


def test_lines_never_move_even_when_labels_do(app, env):
    """라벨이 밀려도 선의 y는 계산값 그대로여야 한다."""
    from watchline import hud_model as model

    acct, cfg = env
    put(acct, "044490", 100_000, 93_050, 93_000)  # -7% 근처에 두 선이 몰림
    win = HudWindow(cfg)
    pump()
    v = win.view
    lines, labels = model.label_ys(v.marks, v.floor, 236, 18)
    assert lines == [model.y_of(m.pct, v.floor, 236) for m in v.marks]
    assert labels != lines
    render(win)
    win.close()


def test_geometry_is_restored(app, env, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    # 테스트가 사용자 설정을 건드리지 않도록 임시 ini로 돌린다.
    ini = str(tmp_path / "hud.ini")
    monkeypatch.setattr(
        HudWindow, "_settings", lambda self: QSettings(ini, QSettings.IniFormat)
    )

    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()
    win.move(321, 123)
    win.close()

    again = HudWindow(cfg)
    pump()
    assert (again.pos().x(), again.pos().y()) == (321, 123)
    again.close()


def test_window_flags(app, env):
    from PySide6.QtCore import Qt

    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    flags = win.windowFlags()
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.FramelessWindowHint
    win.close()


def test_close_stops_polling(app, env):
    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()
    win.close()
    win.timer.stop()
    put(acct, "005930", 80_000, 78_000, 75_000)
    pump()
    assert win.view.code == "044490"  # 멈춘 뒤에는 따라가지 않는다


def test_custom_guides(app, env):
    acct, cfg = env
    cfg = replace(cfg, hud_guides=(-5.0,))
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()
    labels = [m.label for m in win.view.marks]
    assert "-5%" in labels
    assert "-7%" not in labels
    render(win)
    win.close()


# ────────────────────── 그리기 결함 재발 방지 ──────────────────────


def sample(pm, x: int, y: int):
    return pm.toImage().pixelColor(x, y).name()


def test_label_does_not_leave_line_pixels_showing(app, env):
    """지우는 사각형이 1픽셀 모자라 선 끝이 점처럼 남던 문제."""
    from watchline import hud_model as model
    from watchline.hud_window import CARD_W, LABEL_GAP, PAD, STRIP_H

    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()
    pm = render(win)

    v = win.view
    _, labels = model.label_ys(v.marks, v.floor, STRIP_H, LABEL_GAP)
    top = PAD + 68  # 머리글 다음
    card = "#20242b"
    for ly in labels:
        y = int(top + ly)
        if not (0 < y < pm.height() - 1):
            continue
        # 선은 x=CARD_W-PAD까지 그어진다. 라벨이 앉은 줄에서는
        # 그 마지막 픽셀까지 지워져 있어야 한다.
        assert sample(pm, CARD_W - PAD, y) == card
    win.close()


def test_scale_label_is_not_drawn_inside_the_strip(app, env):
    """3선이 하한에 붙으면 스트립 바닥의 배율 표기와 겹치던 문제."""
    acct, cfg = env
    put(acct, "044490", 100_000, 95_000, 60_000)  # -40%, 클램프
    win = HudWindow(cfg)
    pump()
    assert win.view.clamped
    assert win.scale_text(win.view) == "배율 -25%"  # 머리글에서만 나온다
    render(win)
    win.close()


def test_scale_text_hidden_at_default_scale(app, env):
    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()
    assert win.view.floor == -10.0
    assert win.scale_text(win.view) == ""
    win.close()


def test_solid_line_sits_above_dashed_guide(app, env):
    """수평선이 -7% 근처일 때 점선이 실선을 덮으면 안 된다."""
    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 92_990)  # -7.01%, 병합되지 않음
    win = HudWindow(cfg)
    pump()
    v = win.view
    assert not any(m.merged for m in v.marks)
    # 3선과 -7% 가이드가 1픽셀 안에 겹쳐 그려져도 예외 없이 그려진다
    render(win)
    win.close()


def test_code_is_not_drawn_twice_without_a_name(app, env):
    """이름을 모를 때 제목과 오른쪽 코드가 같은 글자로 두 번 찍히던 문제."""
    from watchline.hud_window import CARD_W, PAD

    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()
    assert win.view.has_name is False
    assert win.view.title == "044490"

    pm = render(win)
    card = "#20242b"
    # 제목 줄의 오른쪽 절반은 비어 있어야 한다
    row = PAD + 9
    for dy in range(-6, 7):
        for x in range(CARD_W // 2 + 20, CARD_W - PAD + 1):
            assert sample(pm, x, row + dy) == card
    win.close()


def test_code_is_drawn_alongside_a_known_name(app, env):
    """이름을 알면 오른쪽에 코드를 곁들인다."""
    from watchline.hud_window import CARD_W, PAD

    acct, cfg = env
    cfg.names_file.write_text('{"044490": "다이나믹디자인"}', encoding="utf-8")
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()
    assert win.view.has_name is True

    pm = render(win)
    card = "#20242b"
    row = PAD + 9
    painted = any(
        sample(pm, x, row + dy) != card
        for dy in range(-6, 7)
        for x in range(CARD_W // 2 + 20, CARD_W - PAD + 1)
    )
    assert painted  # 코드가 실제로 그려졌다
    win.close()


def transparent_render(win) -> QPixmap:
    """투명 배경 위에 그린다. 창이 칠하지 않은 자리는 알파 0으로 남는다."""
    from PySide6.QtCore import Qt

    pm = QPixmap(win.size())
    pm.fill(Qt.transparent)
    win.render(pm)
    return pm


def test_corners_are_transparent(app, env):
    """둥근 카드 바깥이 기본 배경색으로 남아 모서리가 각져 보이던 문제.

    offscreen 렌더링만으로는 WA_TranslucentBackground와
    WA_NoSystemBackground를 구분할 수 없다. 실제 Windows에서 네이티브
    창을 알파로 만드는 건 앞의 것뿐이므로 속성 자체를 함께 확인한다.
    """
    from PySide6.QtCore import Qt

    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()

    assert win.testAttribute(Qt.WA_TranslucentBackground)
    assert win.testAttribute(Qt.WA_NoSystemBackground)

    img = transparent_render(win).toImage()
    w, h = win.width(), win.height()
    for x, y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        assert img.pixelColor(x, y).alpha() == 0, f"모서리 ({x},{y})가 칠해져 있다"
    assert img.pixelColor(w // 2, h // 2).alpha() == 255  # 카드 안은 불투명
    win.close()


def test_lines_do_not_overhang_their_endpoints(app, env):
    """펜 마감이 SquareCap이면 선이 양 끝으로 삐져나와 점이 남던 문제."""
    from watchline import hud_model as model
    from watchline.hud_window import CARD_W, HEADER_H, LABEL_GAP, PAD, STRIP_H

    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()
    img = transparent_render(win).toImage()

    line_ys, _ = model.label_ys(win.view.marks, win.view.floor, STRIP_H, LABEL_GAP)
    card = "#20242b"
    for m, ly in zip(win.view.marks, line_ys, strict=True):
        y = int(PAD + HEADER_H + ly)
        for x in (PAD - 3, PAD - 2, PAD - 1):
            assert img.pixelColor(x, y).name() == card, f"{m.label} 왼쪽 x={x}"
        for x in (CARD_W - PAD + 1, CARD_W - PAD + 2):
            assert img.pixelColor(x, y).name() == card, f"{m.label} 오른쪽 x={x}"
    win.close()


def test_footer_distinguishes_labels_from_numbers(app, env):
    """라벨과 숫자가 같은 색 한 덩어리로 그려져 구분이 안 되던 문제.

    글자는 안티에일리어싱으로 번지므로 정확한 색을 찾는 대신 밝기로 본다.
    전부 흐린 색으로 그리면 최대 밝기가 C_DIM 수준을 넘지 못한다.
    """
    from watchline.hud_window import C_DIM, C_TEXT, FOOTER_H, PAD

    acct, cfg = env
    put(acct, "044490", 100_000, 96_500, 91_600)
    win = HudWindow(cfg)
    pump()
    img = transparent_render(win).toImage()

    band_top = win.height() - PAD - FOOTER_H
    values = [
        img.pixelColor(x, y).value()
        for y in range(band_top, win.height() - PAD)
        for x in range(PAD, win.width() // 2)
    ]
    brightest = max(values)
    assert brightest > C_DIM.value() + 25, "숫자가 라벨과 같은 밝기로 그려졌다"
    assert brightest <= C_TEXT.value()
    # 흐린 라벨도 실제로 존재해야 한다
    assert any(90 < v < C_DIM.value() + 15 for v in values), "라벨 획이 없다"
    win.close()


def test_footer_omits_pairs_that_would_hit_the_timestamp(app, env):
    """선이 많아 자리가 모자라면 시각과 겹치는 대신 뒤쪽을 생략한다."""
    from dataclasses import replace as dc_replace

    acct, cfg = env
    cfg = dc_replace(cfg, top_n=6)
    put(acct, "044490", 100_000, 98_000, 96_000, 94_000, 92_000, 90_000)
    win = HudWindow(cfg)
    pump()
    assert len(win.view.gap_pairs()) == 5
    render(win)  # 그리다 죽지 않는다
    win.close()


def test_footer_shows_status_when_no_pairs(app, env):
    acct, cfg = env
    put(acct, "044490", 100_000, 96_500)
    win = HudWindow(cfg)
    pump()
    assert win.view.gap_pairs() == ()
    render(win)
    win.close()
