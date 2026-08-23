"""기록 파일 git 동기화 테스트.

실제 git 저장소를 임시로 만들어 돌린다. git이 없는 환경에서는 건너뛴다.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from watchline import gitsync
from watchline.config import Settings

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git이 설치되어 있지 않습니다"
)


def run(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, check=False)


@pytest.fixture
def repo(tmp_path):
    """원격과 작업 저장소를 만들고 설정을 돌려준다."""
    remote = tmp_path / "remote"
    work = tmp_path / "work"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(remote)], capture_output=True, check=False
    )
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(work)], capture_output=True, check=False
    )
    run(["config", "user.email", "t@example.com"], work)
    run(["config", "user.name", "tester"], work)

    (work / "kospi.json").write_text("{}", encoding="utf-8")
    run(["add", "."], work)
    run(["commit", "-qm", "init"], work)
    run(["push", "-q", "origin", "HEAD:master"], work)
    run(["branch", "-q", "--set-upstream-to=origin/master", "master"], work)

    return dataclasses.replace(
        Settings(),
        project_root=work,
        kospi_file=work / "kospi.json",
        tag_store_file=work / "stock_tags.json",
    )


# ────────────────────────────── 상태 확인 ──────────────────────────────


def test_available_in_repo(repo):
    ok, why = gitsync.available(repo)
    assert ok and why == ""


def test_not_a_repo(tmp_path):
    cfg = dataclasses.replace(Settings(), project_root=tmp_path / "plain")
    (tmp_path / "plain").mkdir()
    ok, why = gitsync.available(cfg)
    assert not ok and "저장소" in why


def test_branch_name(repo):
    assert gitsync.branch(repo) == "master"


def test_pending_zero_when_clean(repo):
    assert gitsync.pending_count(repo) == 0


def test_pending_counts_new_file(repo):
    """새로 생긴 파일(untracked)도 세어야 한다. diff는 이걸 못 본다."""
    (repo.project_root / "stock_tags.json").write_text("{}", encoding="utf-8")
    assert gitsync.pending_count(repo) == 1


def test_pending_counts_modified_file(repo):
    repo.kospi_file.write_text('{"2026-08-18":"up"}', encoding="utf-8")
    assert gitsync.pending_count(repo) == 1


def test_pending_counts_unpushed_commit(repo):
    repo.kospi_file.write_text('{"2026-08-18":"up"}', encoding="utf-8")
    run(["commit", "-qam", "data: test"], repo.project_root)
    assert gitsync.pending_count(repo) == 1


# ────────────────────────────── push ──────────────────────────────


def test_push_commits_and_clears_pending(repo):
    repo.kospi_file.write_text('{"2026-08-18":"down"}', encoding="utf-8")
    res = gitsync.push(repo, day="2026-08-18")
    assert res.ok, res.error
    assert gitsync.pending_count(repo) == 0
    assert any("2026-08-18" in ln for ln in res.lines)


def test_push_includes_untracked_record(repo):
    tags = {"005930": {"date": "2026-08-18", "tags": ["#상한가"]}}
    repo.tag_store_file.write_text(
        json.dumps(tags, ensure_ascii=False), encoding="utf-8"
    )
    assert gitsync.push(repo, day="2026-08-18").ok
    out = subprocess.run(
        ["git", "ls-files", "stock_tags.json"],
        cwd=str(repo.project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert "stock_tags.json" in out.stdout


def test_push_when_nothing_to_do(repo):
    res = gitsync.push(repo, day="2026-08-18")
    assert res.ok
    assert any("없습니다" in ln or "최신" in ln for ln in res.lines)


def test_push_stops_on_unrelated_changes(repo):
    """기록 외 파일이 커밋 안 된 채 남아 있으면 rebase가 막히므로 멈춘다."""
    code = repo.project_root / "code.py"
    code.write_text("print(1)", encoding="utf-8")
    run(["add", "code.py"], repo.project_root)
    run(["commit", "-qm", "add code"], repo.project_root)
    code.write_text("print(2)", encoding="utf-8")

    repo.kospi_file.write_text('{"2026-08-18":"up"}', encoding="utf-8")
    res = gitsync.push(repo, day="2026-08-18")
    assert not res.ok
    assert "code.py" in res.error


def test_push_merges_remote_changes(tmp_path, repo):
    """다른 PC가 먼저 올린 기록이 있어도 양쪽이 모두 살아남는다."""
    other = tmp_path / "other"
    remote = tmp_path / "remote"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(other)],
        capture_output=True,
        check=False,
    )
    run(["config", "user.email", "o@example.com"], other)
    run(["config", "user.name", "other"], other)
    (other / "stock_tags.json").write_text(
        '{"000660":{"date":"2026-08-18","tags":[]}}', encoding="utf-8"
    )
    run(["add", "."], other)
    run(["commit", "-qm", "data: other"], other)
    run(["push", "-q", "origin", "master"], other)

    repo.kospi_file.write_text('{"2026-08-19":"up"}', encoding="utf-8")
    res = gitsync.push(repo, day="2026-08-19")

    assert res.ok, res.error
    assert "2026-08-19" in repo.kospi_file.read_text(encoding="utf-8")
    assert "000660" in repo.tag_store_file.read_text(encoding="utf-8")


# ────────────────────────────── pull ──────────────────────────────


def test_pull_up_to_date(repo):
    res = gitsync.pull(repo)
    assert res.ok
    assert any("최신" in ln for ln in res.lines)


def test_pull_fetches_remote_change(tmp_path, repo):
    other = tmp_path / "other2"
    subprocess.run(
        ["git", "clone", "-q", str(tmp_path / "remote"), str(other)],
        capture_output=True,
        check=False,
    )
    run(["config", "user.email", "o@example.com"], other)
    run(["config", "user.name", "other"], other)
    (other / "kospi.json").write_text('{"2026-08-20":"down"}', encoding="utf-8")
    run(["commit", "-qam", "data: other"], other)
    run(["push", "-q", "origin", "master"], other)

    assert gitsync.pull(repo).ok
    assert "2026-08-20" in repo.kospi_file.read_text(encoding="utf-8")


def test_pull_reports_error_outside_repo(tmp_path):
    cfg = dataclasses.replace(Settings(), project_root=tmp_path / "nowhere")
    (tmp_path / "nowhere").mkdir()
    res = gitsync.pull(cfg)
    assert not res.ok and res.error
