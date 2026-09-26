"""기록 되돌리기.

실제 git 저장소를 만들어 돌린다. 되돌리기는 복구가 안 되는 동작이라
'무엇을 건드리고 무엇을 안 건드리는지'를 실물로 확인해야 한다.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from watchline import gitsync
from watchline.config import Settings


def run(args: list[str], cwd: Path):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


@pytest.fixture
def repo(tmp_path: Path) -> Settings:
    """원격 하나와 작업 사본 하나. 기록 3종이 이미 올라가 있다."""
    remote = tmp_path / "remote"
    remote.mkdir()
    run(["init", "-q", "--bare", "-b", "master", "."], remote)

    work = tmp_path / "work"
    work.mkdir()
    run(["init", "-q", "-b", "master", "."], work)
    run(["config", "user.email", "t@example.com"], work)
    run(["config", "user.name", "tester"], work)
    (work / "kospi.json").write_text('{"2026-09-01":"up"}', encoding="utf-8")
    (work / "stock_tags.json").write_text(
        json.dumps({"005930": {"date": "2026-09-01", "tags": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (work / "names.json").write_text('{"005930":"삼성전자"}', encoding="utf-8")
    (work / "code.py").write_text("print(1)\n", encoding="utf-8")
    run(["add", "."], work)
    run(["commit", "-qm", "init"], work)
    run(["remote", "add", "origin", str(remote)], work)
    run(["push", "-q", "-u", "origin", "master"], work)

    return dataclasses.replace(
        Settings(),
        project_root=work,
        kospi_file=work / "kospi.json",
        tag_store_file=work / "stock_tags.json",
        names_file=work / "names.json",
    )


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ────────────────────────────── 미리보기 ──────────────────────────────


def test_plan_is_empty_when_nothing_changed(repo):
    plan, why = gitsync.plan_revert(repo)
    assert why == ""
    assert plan.empty
    assert plan.ref == "origin/master"
    assert plan.unpushed == 0


def test_plan_lists_uncommitted_changes(repo):
    repo.kospi_file.write_text('{"2026-09-02":"down"}', encoding="utf-8")
    plan, _ = gitsync.plan_revert(repo)
    assert [n for n, _, _ in plan.changes] == ["kospi.json"]
    assert not plan.empty


def test_plan_lists_committed_but_unpushed(repo):
    repo.kospi_file.write_text('{"2026-09-02":"down"}', encoding="utf-8")
    run(["commit", "-qam", "data: 기록"], repo.project_root)
    plan, _ = gitsync.plan_revert(repo)
    assert [n for n, _, _ in plan.changes] == ["kospi.json"]
    assert plan.unpushed == 1


def test_plan_counts_several_files(repo):
    repo.kospi_file.write_text('{"2026-09-02":"down"}', encoding="utf-8")
    repo.names_file.write_text(
        '{"005930":"삼성전자","028670":"팬오션"}', encoding="utf-8"
    )
    plan, _ = gitsync.plan_revert(repo)
    assert sorted(n for n, _, _ in plan.changes) == ["kospi.json", "names.json"]


def test_plan_ignores_code_changes(repo):
    """기록 파일만 본다. 코드가 바뀌었다고 되돌릴 것이 생기면 안 된다."""
    (repo.project_root / "code.py").write_text("print(2)\n", encoding="utf-8")
    plan, _ = gitsync.plan_revert(repo)
    assert plan.empty


def test_plan_reports_file_absent_on_remote(repo):
    """원격에 없던 파일은 되돌릴 기준이 없다."""
    run(["rm", "-q", "--cached", "names.json"], repo.project_root)
    run(["commit", "-qm", "drop names"], repo.project_root)
    run(["push", "-q", "origin", "master"], repo.project_root)
    repo.names_file.write_text('{"005930":"삼성전자"}', encoding="utf-8")

    plan, _ = gitsync.plan_revert(repo)
    assert "names.json" in plan.missing


def test_plan_fails_outside_a_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    plan, why = gitsync.plan_revert(dataclasses.replace(Settings(), project_root=plain))
    assert plan is None
    assert why


# ────────────────────────────── 되돌리기 ──────────────────────────────


def test_revert_restores_uncommitted_change(repo):
    before = read(repo.kospi_file)
    repo.kospi_file.write_text('{"2026-09-02":"down"}', encoding="utf-8")

    res = gitsync.revert(repo)
    assert res.ok, res.error
    assert read(repo.kospi_file) == before
    assert gitsync.pending_count(repo) == 0


def test_revert_restores_committed_but_unpushed(repo):
    before = read(repo.tag_store_file)
    repo.tag_store_file.write_text(
        '{"000660":{"date":"2026-09-02","tags":[]}}', encoding="utf-8"
    )
    run(["commit", "-qam", "data: 기록"], repo.project_root)

    res = gitsync.revert(repo)
    assert res.ok, res.error
    assert read(repo.tag_store_file) == before


def test_revert_leaves_head_matching_remote(repo):
    """커밋까지 된 변경을 되돌리면 HEAD의 내용도 원격과 같아야 한다."""
    repo.kospi_file.write_text('{"2026-09-02":"down"}', encoding="utf-8")
    run(["commit", "-qam", "data: 기록"], repo.project_root)
    gitsync.revert(repo)

    code, out = _diff_head_vs_remote(repo)
    assert out == "", f"HEAD가 원격과 다르다: {out}"


def _diff_head_vs_remote(repo):
    r = run(
        ["diff", "origin/master", "HEAD", "--", *gitsync.TRACKED], repo.project_root
    )
    return r.returncode, r.stdout.strip()


def test_revert_does_not_touch_code(repo):
    """코드 변경은 건드리지 않는다. reset --hard였다면 날아간다."""
    code_file = repo.project_root / "code.py"
    code_file.write_text("print(999)\n", encoding="utf-8")
    repo.kospi_file.write_text('{"2026-09-02":"down"}', encoding="utf-8")

    assert gitsync.revert(repo).ok
    assert read(code_file) == "print(999)\n"


def test_revert_does_not_rewrite_history(repo):
    """이력을 다시 쓰면 다른 PC에서 rebase가 꼬인다."""
    first = run(["rev-parse", "HEAD"], repo.project_root).stdout.strip()
    repo.kospi_file.write_text('{"2026-09-02":"down"}', encoding="utf-8")
    run(["commit", "-qam", "data: 기록"], repo.project_root)
    second = run(["rev-parse", "HEAD"], repo.project_root).stdout.strip()

    gitsync.revert(repo)
    log = run(["log", "--format=%H"], repo.project_root).stdout.split()
    assert first in log and second in log  # 기존 커밋이 그대로 남아 있다


def test_revert_restores_only_changed_files(repo):
    repo.kospi_file.write_text('{"2026-09-02":"down"}', encoding="utf-8")
    res = gitsync.revert(repo)
    assert "kospi.json" in " ".join(res.lines)
    assert "stock_tags.json" not in " ".join(res.lines)


def test_revert_when_nothing_to_do(repo):
    res = gitsync.revert(repo)
    assert res.ok
    assert "되돌릴 기록이 없습니다." in res.lines


def test_revert_streams_steps_as_they_happen(repo):
    repo.kospi_file.write_text('{"2026-09-02":"down"}', encoding="utf-8")
    seen: list[str] = []
    res = gitsync.revert(repo, on_step=seen.append)
    assert seen == res.lines  # 콜백과 기록이 같은 내용을 같은 순서로 받는다
    assert any("되돌리는 중" in x for x in seen)


def test_revert_fails_without_remote(tmp_path):
    work = tmp_path / "solo"
    work.mkdir()
    run(["init", "-q", "-b", "master", "."], work)
    run(["config", "user.email", "t@example.com"], work)
    run(["config", "user.name", "t"], work)
    (work / "kospi.json").write_text("{}", encoding="utf-8")
    run(["add", "."], work)
    run(["commit", "-qm", "init"], work)

    cfg = dataclasses.replace(
        Settings(), project_root=work, kospi_file=work / "kospi.json"
    )
    res = gitsync.revert(cfg)
    assert not res.ok
    assert res.error


def test_revert_survives_offline_fetch(repo, monkeypatch):
    """원격에 못 닿아도 마지막으로 받아둔 상태로는 되돌릴 수 있어야 한다."""
    real = gitsync._run

    def _fail_fetch(args, root):
        if args and args[0] == "fetch":
            return 1, "네트워크 없음"
        return real(args, root)

    monkeypatch.setattr(gitsync, "_run", _fail_fetch)
    before = read(repo.kospi_file)
    repo.kospi_file.write_text('{"2026-09-02":"down"}', encoding="utf-8")

    res = gitsync.revert(repo)
    assert res.ok, res.error
    assert read(repo.kospi_file) == before
    assert any("받아오지 못해" in x for x in res.lines)


def test_revert_picks_up_remote_changes_made_elsewhere(tmp_path, repo):
    """다른 PC가 올린 최신 기록이 기준이 되어야 한다."""
    other = tmp_path / "other"
    run(["clone", "-q", str(tmp_path / "remote"), str(other)], tmp_path)
    run(["config", "user.email", "o@example.com"], other)
    run(["config", "user.name", "o"], other)
    (other / "kospi.json").write_text('{"2026-09-05":"up"}', encoding="utf-8")
    run(["commit", "-qam", "data: other"], other)
    run(["push", "-q", "origin", "master"], other)

    repo.kospi_file.write_text('{"2026-09-09":"down"}', encoding="utf-8")
    assert gitsync.revert(repo).ok
    assert read(repo.kospi_file) == '{"2026-09-05":"up"}'
