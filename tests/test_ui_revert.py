"""기록 되돌리기 버튼.

git은 test_gitsync_revert가 실물로 확인하므로, 여기서는 창이
'언제 묻고, 무엇을 보여주고, 언제 실제로 부르는지'만 본다.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from watchline import gitsync, ui  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, monkeypatch):
    monkeypatch.setattr(gitsync, "available", lambda cfg=None: (True, ""))
    monkeypatch.setattr(gitsync, "pending_count", lambda cfg=None: 0)
    ui.apply_theme(app)
    w = ui.MainWindow()
    yield w
    w.dirty = False
    w.sync_ready = False
    w.close()


def plan(changes=(("kospi.json", 1, 1),), missing=(), unpushed=0, fetched=True):
    return gitsync.RevertPlan(
        ref="origin/master",
        changes=list(changes),
        missing=list(missing),
        fetched=fetched,
        unpushed=unpushed,
    )


def asked(monkeypatch, value=QMessageBox.No):
    """확인창을 가로채 본문과 인자를 모두 기록한다."""

    class Seen(list):
        args: list[tuple] = []

    seen = Seen()
    seen.args = []

    def _q(parent, title, text, *a, **k):
        seen.append(text)
        seen.args.append(a)
        return value

    monkeypatch.setattr(QMessageBox, "question", _q)
    return seen


def quiet(monkeypatch):
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: None)


# ────────────────────────────── 버튼 ──────────────────────────────


def test_button_exists_without_a_shortcut(win):
    """되돌리기에 단축키를 달면 손이 미끄러질 경로가 하나 늘어난다."""
    labels = [a.text() for a in win.toolbar.actions()]
    assert "기록 되돌리기" in labels
    assert win.act_revert.shortcut().isEmpty()


# ────────────────────────────── 묻는 조건 ──────────────────────────────


def test_nothing_to_revert_does_not_ask(win, monkeypatch):
    quiet(monkeypatch)
    seen = asked(monkeypatch)
    monkeypatch.setattr(gitsync, "plan_revert", lambda cfg=None: (plan(changes=()), ""))
    called = []
    monkeypatch.setattr(gitsync, "revert", lambda *a, **k: called.append(1))

    win.on_revert()

    assert seen == []
    assert called == []


def test_unavailable_repo_does_not_ask(win, monkeypatch):
    quiet(monkeypatch)
    seen = asked(monkeypatch)
    monkeypatch.setattr(gitsync, "plan_revert", lambda cfg=None: (None, "저장소 아님"))
    called = []
    monkeypatch.setattr(gitsync, "revert", lambda *a, **k: called.append(1))

    win.on_revert()

    assert seen == []
    assert called == []
    assert "저장소 아님" in win.log.toPlainText()


def test_default_button_is_no(win, monkeypatch):
    """엔터를 습관적으로 쳐도 되돌아가지 않아야 한다."""
    quiet(monkeypatch)
    seen = asked(monkeypatch, QMessageBox.No)
    monkeypatch.setattr(gitsync, "plan_revert", lambda cfg=None: (plan(), ""))
    monkeypatch.setattr(gitsync, "revert", lambda *a, **k: gitsync.Result(ok=True))

    win.on_revert()

    buttons, default = seen.args[0]
    assert default == QMessageBox.No
    assert buttons == QMessageBox.Yes | QMessageBox.No


def test_declining_does_not_revert(win, monkeypatch):
    quiet(monkeypatch)
    asked(monkeypatch, QMessageBox.No)
    monkeypatch.setattr(gitsync, "plan_revert", lambda cfg=None: (plan(), ""))
    called = []
    monkeypatch.setattr(gitsync, "revert", lambda *a, **k: called.append(1))

    win.on_revert()

    assert called == []
    assert "취소했습니다" in win.log.toPlainText()


def test_confirming_calls_revert(win, monkeypatch):
    quiet(monkeypatch)
    asked(monkeypatch, QMessageBox.Yes)
    monkeypatch.setattr(gitsync, "plan_revert", lambda cfg=None: (plan(), ""))
    called = []

    def _revert(cfg=None, on_step=None):
        called.append(1)
        if on_step:
            on_step("기록 1개를 되돌렸습니다")
        return gitsync.Result(ok=True)

    monkeypatch.setattr(gitsync, "revert", _revert)

    win.on_revert()

    assert called == [1]
    log = win.log.toPlainText()
    assert "기록 1개를 되돌렸습니다" in log
    assert "완료되었습니다" in log


def test_ignored_while_syncing(win, monkeypatch):
    quiet(monkeypatch)
    seen = asked(monkeypatch)
    called = []
    monkeypatch.setattr(gitsync, "plan_revert", lambda cfg=None: called.append(1))
    win.sync_thread = object()  # 동기화 중인 척
    try:
        win.on_revert()
    finally:
        win.sync_thread = None
    assert seen == [] and called == []


# ────────────────────────────── 확인창 문구 ──────────────────────────────


def test_prompt_lists_each_file_and_line_counts(win):
    text = win._revert_prompt(
        plan(changes=(("kospi.json", 2, 1), ("stock_tags.json", 14, 3)))
    )
    assert "kospi.json  +2 −1 줄" in text
    assert "stock_tags.json  +14 −3 줄" in text
    assert "origin/master" in text
    assert "복구할 수 없습니다" in text


def test_prompt_mentions_unpushed_commits(win):
    assert "커밋 2개" in win._revert_prompt(plan(unpushed=2))
    assert "커밋" not in win._revert_prompt(plan(unpushed=0)).split("되돌린 뒤")[0]


def test_prompt_mentions_files_absent_on_remote(win):
    text = win._revert_prompt(plan(missing=["names.json"]))
    assert "원격에 없어 그대로 두는 파일: names.json" in text


def test_prompt_warns_when_offline(win):
    assert "받아오지 못해" in win._revert_prompt(plan(fetched=False))
    assert "받아오지 못해" not in win._revert_prompt(plan(fetched=True))


# ────────────────────────────── 뒤처리 ──────────────────────────────


def test_records_are_reloaded_after_revert(win, monkeypatch):
    quiet(monkeypatch)
    asked(monkeypatch, QMessageBox.Yes)
    monkeypatch.setattr(gitsync, "plan_revert", lambda cfg=None: (plan(), ""))
    monkeypatch.setattr(
        gitsync, "revert", lambda cfg=None, on_step=None: gitsync.Result(ok=True)
    )
    done = []
    monkeypatch.setattr(win, "reload_store", lambda *a, **k: done.append("store"))
    monkeypatch.setattr(win, "reload_market", lambda *a, **k: done.append("market"))

    win.on_revert()

    assert done == ["store", "market"]


def test_failure_is_reported_and_records_untouched(win, monkeypatch):
    quiet(monkeypatch)
    asked(monkeypatch, QMessageBox.Yes)
    monkeypatch.setattr(gitsync, "plan_revert", lambda cfg=None: (plan(), ""))
    monkeypatch.setattr(
        gitsync,
        "revert",
        lambda cfg=None, on_step=None: gitsync.Result(ok=False, error="충돌"),
    )
    done = []
    monkeypatch.setattr(win, "reload_store", lambda *a, **k: done.append("store"))

    win.on_revert()

    assert done == []  # 실패했으면 다시 읽을 것도 없다
    assert "실패 — 충돌" in win.log.toPlainText()


def test_toolbar_is_unlocked_afterwards(win, monkeypatch):
    quiet(monkeypatch)
    asked(monkeypatch, QMessageBox.Yes)
    monkeypatch.setattr(gitsync, "plan_revert", lambda cfg=None: (plan(), ""))
    monkeypatch.setattr(
        gitsync, "revert", lambda cfg=None, on_step=None: gitsync.Result(ok=True)
    )
    actions = [a for a in win.toolbar.actions() if not a.isSeparator()]
    before = {a: a.isEnabled() for a in actions}

    win.on_revert()

    assert {a: a.isEnabled() for a in actions} == before


def test_toolbar_is_unlocked_even_when_git_raises(win, monkeypatch):
    quiet(monkeypatch)
    actions = [a for a in win.toolbar.actions() if not a.isSeparator()]
    before = {a: a.isEnabled() for a in actions}

    def _boom(cfg=None):
        raise RuntimeError("터짐")

    monkeypatch.setattr(gitsync, "plan_revert", _boom)
    with pytest.raises(RuntimeError):
        win.on_revert()

    assert {a: a.isEnabled() for a in actions} == before
