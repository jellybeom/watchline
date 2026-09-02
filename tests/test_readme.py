"""README가 실제 파일 구성과 어긋나지 않는지 확인한다.

모듈이나 테스트를 추가하고 README를 고치는 걸 잊기 쉽다. 문서가 조용히
낡아가는 걸 막으려면 사람이 기억하는 대신 테스트가 붙잡아야 한다.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


def structure_block(readme: str) -> str:
    """'프로젝트 구조' 절의 코드 블록만 떼어낸다."""
    i = readme.index("## 프로젝트 구조")
    start = readme.index("```", i) + 3
    return readme[start : readme.index("```", start)]


@pytest.mark.parametrize("path", sorted((ROOT / "watchline").glob("*.py")))
def test_every_module_is_listed(readme, path: Path):
    if path.name == "__init__.py":
        pytest.skip("패키지 표시용 빈 파일")
    assert path.name in structure_block(
        readme
    ), f"{path.name}이 README 프로젝트 구조에 없습니다"


@pytest.mark.parametrize("path", sorted((ROOT / "tests").glob("test_*.py")))
def test_every_test_file_is_listed(readme, path: Path):
    assert path.name in structure_block(
        readme
    ), f"{path.name}이 README 프로젝트 구조에 없습니다"


def test_structure_lists_nothing_that_vanished(readme):
    """반대 방향. 지운 파일이 목록에 남아 있으면 안 된다."""
    listed = set(re.findall(r"([\w_]+\.py)", structure_block(readme)))
    actual = {p.name for p in (ROOT / "watchline").glob("*.py")}
    actual |= {p.name for p in (ROOT / "tests").glob("*.py")}
    assert listed <= actual, f"README에만 있는 파일: {sorted(listed - actual)}"


@pytest.mark.parametrize("name", ["run.bat", "hud.bat", "pyproject.toml", "tags.txt"])
def test_root_files_are_listed(readme, name: str):
    if not (ROOT / name).exists():
        pytest.skip(f"{name}이 저장소에 없음")
    assert name in structure_block(readme)


def test_every_entry_point_is_documented(readme):
    """pyproject의 실행 명령이 사용법에 나와야 한다."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})
    assert scripts, "실행 명령이 정의되어 있지 않다"
    for name in scripts:
        # 부분 일치는 안 된다. watchline-hudX도 watchline-hud를 포함한다.
        assert re.search(
            rf"(?<![\w-]){re.escape(name)}(?![\w-])", readme
        ), f"실행 명령 {name}이 README에 없습니다"


def test_record_files_are_listed(readme):
    """git으로 동기화하는 기록 파일과 HUD 캐시."""
    for name in ("kospi.json", "stock_tags.json", "names.json"):
        assert name in structure_block(readme), f"{name}이 README에 없습니다"


def test_lint_command_points_at_real_paths(readme):
    """예전에 존재하지 않는 src/를 가리키고 있었다."""
    m = re.search(r"ruff check ([\w /]+)", readme)
    assert m, "ruff 명령이 README에 없습니다"
    for target in m.group(1).split():
        assert (ROOT / target).is_dir(), f"ruff 대상 {target}이 존재하지 않습니다"
