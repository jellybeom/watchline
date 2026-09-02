"""동기화를 작업 스레드로 옮긴 뒤의 동작 확인.

git을 실제로 돌리지 않고 gitsync.push를 가로채, 느린 동기화 도중에도
창이 살아 있는지·툴바가 잠기는지·끝난 뒤 원래대로 돌아오는지를 본다.
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from watchline import gitsync, ui  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, monkeypatch):
    """동기화가 가능한 상태로 보이는 창."""
    monkeypatch.setattr(gitsync, "available", lambda cfg=None: (True, ""))
    monkeypatch.setattr(gitsync, "pending_count", lambda cfg=None: 2)
    ui.apply_theme(app)
    w = ui.MainWindow()
    yield w
    if w.syncing:
        wait_until(lambda: not w.syncing, 5.0)
    # closeEvent가 "올리지 않은 기록이 있습니다" 대화상자를 띄우면
    # 화면 없는 환경에서는 영영 멈춘다. 물을 거리를 없애고 닫는다.
    w.dirty = False
    w.sync_ready = False
    w.close()


def pump(ms: float = 50) -> None:
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.002)


def wait_until(cond, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def slow_push(
    steps=("커밋했습니다", "원격 변경을 받는 중…", "올리는 중…"),
    delay=0.05,
    ok=True,
    error="",
):
    """단계마다 쉬어가는 가짜 push."""

    def _push(cfg=None, day=None, on_step=None):
        res = gitsync.Result(ok=ok, error=error, on_step=on_step)
        for s in steps:
            time.sleep(delay)
            res.say(s)
        return res

    return _push


# ────────────────────────── gitsync 쪽 ──────────────────────────


def test_on_step_is_called_in_order():
    seen = []
    res = gitsync.Result(ok=True, on_step=seen.append)
    res.say("가")
    res.say("나")
    assert seen == ["가", "나"] == res.lines


def test_result_without_callback_still_records():
    res = gitsync.Result(ok=True)
    res.say("가")
    assert res.lines == ["가"]


def test_on_step_absence_does_not_break_equality():
    a = gitsync.Result(ok=True, lines=["가"])
    b = gitsync.Result(ok=True, lines=["가"], on_step=print)
    assert a == b  # 콜백은 비교에서 빠진다


# ────────────────────────── 창 동작 ──────────────────────────


def test_sync_runs_off_the_gui_thread(win, monkeypatch):
    """동기화가 도는 동안에도 이벤트 루프가 돌아야 한다."""
    threads = []

    def _push(cfg=None, day=None, on_step=None):
        threads.append(QThread.currentThread())
        time.sleep(0.15)
        return gitsync.Result(ok=True, on_step=on_step)

    monkeypatch.setattr(gitsync, "push", _push)
    gui = QThread.currentThread()

    win.on_sync()
    ticks = 0
    while win.syncing and ticks < 2000:
        QApplication.processEvents()  # 얼어 있으면 여기서 못 돈다
        ticks += 1
        time.sleep(0.001)

    assert not win.syncing
    assert threads and threads[0] is not gui, "GUI 스레드에서 돌았다"
    assert ticks > 5, "동기화 중 이벤트 루프가 돌지 않았다"


def test_toolbar_is_locked_while_syncing_and_restored_after(win, monkeypatch):
    monkeypatch.setattr(gitsync, "push", slow_push())
    actions = [a for a in win.toolbar.actions() if not a.isSeparator()]
    before = {a: a.isEnabled() for a in actions}
    assert any(before.values())

    win.on_sync()
    pump(20)
    assert win.syncing
    assert not any(a.isEnabled() for a in actions), "잠기지 않은 버튼이 있다"

    assert wait_until(lambda: not win.syncing)
    assert {a: a.isEnabled() for a in actions} == before, "원래 상태로 안 돌아왔다"


def test_lock_does_not_enable_previously_disabled_actions(win, monkeypatch):
    monkeypatch.setattr(gitsync, "push", slow_push())
    victim = next(a for a in win.toolbar.actions() if not a.isSeparator())
    victim.setEnabled(False)

    win.on_sync()
    assert wait_until(lambda: not win.syncing)
    assert not victim.isEnabled(), "꺼져 있던 버튼이 켜졌다"


def test_steps_stream_to_the_log_as_they_happen(win, monkeypatch):
    monkeypatch.setattr(gitsync, "push", slow_push(delay=0.08))
    win.on_sync()

    assert wait_until(lambda: "원격 변경을 받는 중" in win.log.toPlainText(), 3.0)
    # 아직 끝나지 않았는데도 중간 단계가 이미 보여야 한다
    assert wait_until(lambda: not win.syncing)
    text = win.log.toPlainText()
    assert text.index("원격 변경을 받는 중") < text.index("올리는 중")
    assert "완료되었습니다" in text


def test_second_click_is_ignored_while_running(win, monkeypatch):
    calls = []

    def _push(cfg=None, day=None, on_step=None):
        calls.append(1)
        time.sleep(0.12)
        return gitsync.Result(ok=True, on_step=on_step)

    monkeypatch.setattr(gitsync, "push", _push)
    win.on_sync()
    pump(20)
    win.on_sync()
    win.on_sync()
    assert wait_until(lambda: not win.syncing)
    assert calls == [1], "동기화가 겹쳐 돌았다"


def test_failure_unlocks_the_toolbar(win, monkeypatch):
    monkeypatch.setattr(gitsync, "push", slow_push(steps=(), ok=False, error="망함"))
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *a, **k: None)
    actions = [a for a in win.toolbar.actions() if not a.isSeparator()]

    win.on_sync()
    assert wait_until(lambda: not win.syncing)
    assert any(a.isEnabled() for a in actions), "실패 후 잠긴 채로 남았다"
    assert "실패" in win.log.toPlainText()


def test_worker_exception_does_not_leave_ui_locked(win, monkeypatch):
    """스레드에서 예외가 터져도 창이 영영 잠기면 안 된다."""

    def _boom(cfg=None, day=None, on_step=None):
        raise RuntimeError("터짐")

    monkeypatch.setattr(gitsync, "push", _boom)
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *a, **k: None)
    actions = [a for a in win.toolbar.actions() if not a.isSeparator()]

    win.on_sync()
    assert wait_until(lambda: not win.syncing)
    assert any(a.isEnabled() for a in actions)
    assert "RuntimeError" in win.log.toPlainText()


def test_thread_is_cleaned_up(win, monkeypatch):
    monkeypatch.setattr(gitsync, "push", slow_push())
    win.on_sync()
    assert wait_until(lambda: not win.syncing)
    assert win.sync_thread is None
    assert win.sync_worker is None


def test_close_is_refused_while_syncing(win, monkeypatch):
    from PySide6.QtGui import QCloseEvent

    monkeypatch.setattr(gitsync, "push", slow_push(delay=0.08))
    monkeypatch.setattr(ui.QMessageBox, "information", lambda *a, **k: None)

    win.on_sync()
    pump(20)
    assert win.syncing
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert not ev.isAccepted(), "동기화 중에 창이 닫혔다"
    assert wait_until(lambda: not win.syncing)


def test_drop_is_refused_while_syncing(win, monkeypatch):
    monkeypatch.setattr(gitsync, "push", slow_push(delay=0.08))
    opened = []
    monkeypatch.setattr(
        win, "open_files", lambda paths, append=True: opened.append(paths)
    )
    monkeypatch.setattr(win, "_dropped_csv", lambda event: ["/tmp/a.csv"])

    class FakeEvent:
        def __init__(self):
            self.accepted = False
            self.ignored = False

        def acceptProposedAction(self):
            self.accepted = True

        def ignore(self):
            self.ignored = True

    win.on_sync()
    pump(20)
    ev = FakeEvent()
    win.dropEvent(ev)
    assert ev.ignored and not opened, "동기화 중에 파일이 열렸다"
    assert wait_until(lambda: not win.syncing)


def test_sync_blocked_when_git_unavailable(win, monkeypatch):
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *a, **k: None)
    called = []
    monkeypatch.setattr(gitsync, "push", lambda *a, **k: called.append(1))
    win.sync_ready = False
    win.sync_why = "git 없음"
    win.on_sync()
    pump(20)
    assert not win.syncing
    assert called == []
