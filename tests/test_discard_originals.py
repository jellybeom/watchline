"""저장 뒤 원본 입력 파일을 치우는 동작.

실제 휴지통을 쓰면 테스트가 환경에 끌려다니므로 send2trash를 가로채
'무엇을, 언제, 몇 개나' 넘겼는지만 본다. 지우면 안 되는 파일을 넘기지
않는지가 핵심이다.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from watchline import ui  # noqa: E402

CSV = "종목코드,종목명\n'005930',삼성전자\n'000660',SK하이닉스\n"
CSV2 = "종목코드,종목명\n'028670',팬오션\n"


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def trashed(monkeypatch):
    """휴지통으로 넘어간 경로를 모은다."""
    seen: list[str] = []
    monkeypatch.setattr(ui, "send2trash", seen.append)
    return seen


@pytest.fixture
def win(app, monkeypatch, tmp_path):
    monkeypatch.setattr(ui.gitsync, "available", lambda cfg=None: (False, "테스트"))
    monkeypatch.setattr(ui.names, "update_from", lambda rows, path=None: 0)
    ui.apply_theme(app)
    w = ui.MainWindow()
    # 기록 파일이 저장소의 진짜 파일을 건드리지 않게 임시 경로로 돌린다.
    w.cfg = dataclasses.replace(
        w.cfg,
        tag_store_file=tmp_path / "tags.json",
        names_file=tmp_path / "names.json",
        kospi_file=tmp_path / "kospi.json",
    )
    yield w
    w.dirty = False
    w.sync_ready = False
    w.close()


def answer(monkeypatch, value):
    """확인창의 응답을 고정하고, 실제로 물었는지 기록한다."""
    asked: list[str] = []

    def _q(parent, title, text, *a, **k):
        asked.append(text)
        return value

    monkeypatch.setattr(QMessageBox, "question", _q)
    return asked


def make(tmp_path: Path, name: str, body: str = CSV) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="cp949")
    return p


def save_to(win, monkeypatch, path: Path):
    monkeypatch.setattr(
        ui.QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), "")
    )
    win.on_save()


# ────────────────────────────── 후보 추적 ──────────────────────────────


def test_opening_records_originals(win, tmp_path, monkeypatch):
    a, b = make(tmp_path, "a.csv"), make(tmp_path, "b.csv", CSV2)
    win.open_files([str(a), str(b)], append=False)
    assert [p.name for p in win.originals] == ["a.csv", "b.csv"]


def test_reset_clears_originals(win, tmp_path, monkeypatch):
    win.open_files([str(make(tmp_path, "a.csv"))], append=False)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    win.on_reset()
    assert win.originals == []


def test_reopening_without_append_clears_originals(win, tmp_path, monkeypatch):
    win.open_files([str(make(tmp_path, "a.csv"))], append=False)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    win.open_files([str(make(tmp_path, "b.csv", CSV2))], append=False)
    assert [p.name for p in win.originals] == ["b.csv"]


# ────────────────────────────── 삭제 동작 ──────────────────────────────


def test_save_trashes_originals_after_confirmation(win, tmp_path, monkeypatch, trashed):
    a, b = make(tmp_path, "a.csv"), make(tmp_path, "b.csv", CSV2)
    win.open_files([str(a), str(b)], append=False)
    asked = answer(monkeypatch, QMessageBox.Yes)

    save_to(win, monkeypatch, tmp_path / "합본.csv")

    assert len(asked) == 1
    assert "2개" in asked[0]
    assert sorted(Path(p).name for p in trashed) == ["a.csv", "b.csv"]
    assert win.originals == []


def test_declining_keeps_every_file(win, tmp_path, monkeypatch, trashed):
    a = make(tmp_path, "a.csv")
    win.open_files([str(a)], append=False)
    answer(monkeypatch, QMessageBox.No)

    save_to(win, monkeypatch, tmp_path / "합본.csv")

    assert trashed == []
    assert a.exists()
    assert [p.name for p in win.originals] == ["a.csv"]  # 다음 저장 때 다시 묻는다


def test_saved_file_is_never_trashed(win, tmp_path, monkeypatch, trashed):
    """입력 파일에 덮어쓰기로 저장하면 그건 방금 만든 결과물이다."""
    a, b = make(tmp_path, "a.csv"), make(tmp_path, "b.csv", CSV2)
    win.open_files([str(a), str(b)], append=False)
    answer(monkeypatch, QMessageBox.Yes)

    save_to(win, monkeypatch, a)  # a.csv에 덮어쓴다

    assert [Path(p).name for p in trashed] == ["b.csv"]
    assert a.exists()


def test_no_prompt_when_only_target_remains(win, tmp_path, monkeypatch, trashed):
    a = make(tmp_path, "a.csv")
    win.open_files([str(a)], append=False)
    asked = answer(monkeypatch, QMessageBox.Yes)

    save_to(win, monkeypatch, a)  # 열었던 그 파일에 저장

    assert asked == []  # 지울 게 없으면 묻지 않는다
    assert trashed == []


def test_second_save_does_not_offer_the_first_output(
    win, tmp_path, monkeypatch, trashed
):
    """저장 결과물이 다음 저장 때 원본으로 둔갑하면 안 된다."""
    a = make(tmp_path, "a.csv")
    win.open_files([str(a)], append=False)
    answer(monkeypatch, QMessageBox.Yes)
    save_to(win, monkeypatch, tmp_path / "1차.csv")
    trashed.clear()

    asked = answer(monkeypatch, QMessageBox.Yes)
    save_to(win, monkeypatch, tmp_path / "2차.csv")

    assert asked == []
    assert trashed == []
    assert (tmp_path / "1차.csv").exists()


def test_missing_original_is_skipped(win, tmp_path, monkeypatch, trashed):
    """탐색기에서 이미 지운 파일은 조용히 넘어간다."""
    a, b = make(tmp_path, "a.csv"), make(tmp_path, "b.csv", CSV2)
    win.open_files([str(a), str(b)], append=False)
    b.unlink()
    answer(monkeypatch, QMessageBox.Yes)

    save_to(win, monkeypatch, tmp_path / "합본.csv")

    assert [Path(p).name for p in trashed] == ["a.csv"]


def test_nothing_is_trashed_when_save_fails(win, tmp_path, monkeypatch, trashed):
    """저장이 실패했는데 원본을 지우면 데이터가 사라진다."""
    a = make(tmp_path, "a.csv")
    win.open_files([str(a)], append=False)
    answer(monkeypatch, QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(
        ui.watchlist, "save", lambda *a, **k: (_ for _ in ()).throw(OSError("디스크"))
    )

    save_to(win, monkeypatch, tmp_path / "합본.csv")

    assert trashed == []
    assert a.exists()
    assert [p.name for p in win.originals] == ["a.csv"]


def test_cancelled_dialog_trashes_nothing(win, tmp_path, monkeypatch, trashed):
    a = make(tmp_path, "a.csv")
    win.open_files([str(a)], append=False)
    answer(monkeypatch, QMessageBox.Yes)
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))

    win.on_save()

    assert trashed == []
    assert a.exists()


# ────────────────────────────── 실패 처리 ──────────────────────────────


def test_locked_file_is_reported_and_kept(win, tmp_path, monkeypatch):
    """엑셀이 잡고 있으면 권한 오류가 난다. 나머지는 계속 지운다."""
    a, b = make(tmp_path, "a.csv"), make(tmp_path, "b.csv", CSV2)
    win.open_files([str(a), str(b)], append=False)
    answer(monkeypatch, QMessageBox.Yes)

    def _trash(path):
        if path.endswith("a.csv"):
            raise PermissionError("다른 프로그램이 사용 중")

    monkeypatch.setattr(ui, "send2trash", _trash)
    warned: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda parent, title, text, *a, **k: warned.append(text)
    )

    save_to(win, monkeypatch, tmp_path / "합본.csv")

    assert warned and "a.csv" in warned[0]
    assert [p.name for p in win.originals] == ["a.csv"]  # 실패한 것만 남는다
    assert "삭제 실패" in win.log.toPlainText()


def test_partial_failure_still_reports_success_count(win, tmp_path, monkeypatch):
    a, b = make(tmp_path, "a.csv"), make(tmp_path, "b.csv", CSV2)
    win.open_files([str(a), str(b)], append=False)
    answer(monkeypatch, QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(
        ui,
        "send2trash",
        lambda p: (_ for _ in ()).throw(OSError("x")) if p.endswith("a.csv") else None,
    )

    save_to(win, monkeypatch, tmp_path / "합본.csv")

    log = win.log.toPlainText()
    assert "1개를 휴지통으로 보냈습니다" in log
    assert "삭제 실패" in log
