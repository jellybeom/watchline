"""기록 파일 git 동기화.

여러 PC를 오가며 쓸 때 kospi.json / stock_tags.json을 맞춘다.
UI에 의존하지 않으며, 모든 함수는 예외 대신 결과 객체를 돌려준다.

git 명령은 순서가 중요하다. 커밋하지 않은 변경이 남아 있으면 rebase가
거부되므로, 기록을 먼저 커밋한 뒤 pull하고 마지막에 push한다.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .config import Settings, settings

TRACKED = ("kospi.json", "stock_tags.json")
TIMEOUT = 60


@dataclass
class Result:
    ok: bool
    lines: list[str] = field(default_factory=list)  # 사람이 읽을 진행 기록
    error: str = ""
    # 진행 상황을 즉시 받아보고 싶은 쪽이 넘긴다. 끝난 뒤 lines를 훑으면
    # 오래 걸리는 단계에서 아무 소식이 없어 멈춘 것처럼 보인다.
    on_step: Callable[[str], None] | None = field(
        default=None, repr=False, compare=False
    )

    def say(self, msg: str) -> None:
        self.lines.append(msg)
        if self.on_step is not None:
            self.on_step(msg)


def _run(args: list[str], cwd: Path) -> tuple[int, str]:
    """git 명령 하나를 돌린다. 반환: (종료코드, 출력)"""
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
        )
    except FileNotFoundError:
        return 127, "git을 찾을 수 없습니다."
    except subprocess.TimeoutExpired:
        return 124, f"시간이 초과되었습니다({TIMEOUT}초). 네트워크를 확인하세요."
    return p.returncode, (p.stdout + p.stderr).strip()


def available(cfg: Settings | None = None) -> tuple[bool, str]:
    """동기화를 쓸 수 있는 상태인지. 반환: (가능, 이유)"""
    cfg = cfg or settings
    code, out = _run(["rev-parse", "--is-inside-work-tree"], cfg.project_root)
    if code == 127:
        return False, "git이 설치되어 있지 않습니다."
    if code != 0:
        return False, f"git 저장소가 아닙니다: {cfg.project_root}"
    return True, ""


def branch(cfg: Settings | None = None) -> str:
    cfg = cfg or settings
    code, out = _run(["rev-parse", "--abbrev-ref", "HEAD"], cfg.project_root)
    return out if code == 0 else ""


def pending_count(cfg: Settings | None = None) -> int:
    """아직 올리지 않은 것의 개수.

    커밋 안 된 기록 변경과 push 안 된 커밋을 합쳐 센다.
    status --porcelain을 쓰는 이유는 diff가 새로 생긴 파일(untracked)을
    보지 못하기 때문이다.
    """
    cfg = cfg or settings
    root = cfg.project_root
    n = 0

    code, out = _run(["status", "--porcelain", "--", *TRACKED], root)
    if code == 0:
        n += len([ln for ln in out.splitlines() if ln.strip()])

    code, out = _run(["rev-list", "--count", "@{u}..HEAD"], root)
    if code == 0 and out.isdigit():
        n += int(out)
    return n


def _ensure_upstream(res: Result, root: Path, br: str) -> bool:
    """업스트림이 없으면 origin/<브랜치>로 연결한다. 반환: 이미 연결돼 있었나."""
    code, _ = _run(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root)
    if code == 0:
        return True
    code, _ = _run(["branch", f"--set-upstream-to=origin/{br}", br], root)
    if code == 0:
        res.say(f"업스트림을 origin/{br}로 연결했습니다.")
        return True
    res.say("원격에 브랜치가 없어 push할 때 함께 만듭니다.")
    return False


def pull(
    cfg: Settings | None = None,
    on_step: Callable[[str], None] | None = None,
) -> Result:
    """원격 기록을 내려받는다. 읽기만 하므로 시작할 때 자동으로 불러도 안전하다."""
    cfg = cfg or settings
    res = Result(ok=False, on_step=on_step)
    root = cfg.project_root

    okay, why = available(cfg)
    if not okay:
        res.error = why
        return res

    br = branch(cfg)
    if not br:
        res.error = "현재 브랜치를 알 수 없습니다."
        return res

    code, out = _run(["pull", "--rebase", "origin", br], root)
    if code != 0:
        res.error = out.splitlines()[-1] if out else "pull에 실패했습니다."
        return res

    res.ok = True
    res.say(
        "이미 최신입니다."
        if "up to date" in out.lower()
        else "원격 기록을 내려받았습니다."
    )
    return res


def push(
    cfg: Settings | None = None,
    day: str | None = None,
    on_step: Callable[[str], None] | None = None,
) -> Result:
    """기록을 커밋하고 원격에 올린다. 커밋 → pull → push 순."""
    cfg = cfg or settings
    res = Result(ok=False, on_step=on_step)
    root = cfg.project_root

    okay, why = available(cfg)
    if not okay:
        res.error = why
        return res

    br = branch(cfg)
    if not br:
        res.error = "현재 브랜치를 알 수 없습니다."
        return res

    # 새로 생긴 파일도 잡히도록 add를 먼저 한다. diff는 추적 중인 것만 보기 때문이다.
    present = [n for n in TRACKED if (root / n).exists()]
    for name in present:
        _run(["add", "--", name], root)

    if not present:
        res.error = "올릴 기록 파일이 없습니다."
        return res

    code, _ = _run(["diff", "--cached", "--quiet", "--", *present], root)
    if code == 1:
        msg = f"data: {day or date.today().isoformat()} 기록 갱신"
        # 경로를 한정해 다른 스테이지 내용이 섞이지 않게 한다.
        code, out = _run(["commit", "-m", msg, "--", *present], root)
        if code != 0:
            res.error = out.splitlines()[-1] if out else "commit에 실패했습니다."
            return res
        res.say(f"커밋했습니다 — {msg}")
    else:
        res.say("새로 커밋할 기록 변경이 없습니다.")

    # 기록 외에 커밋 안 된 변경이 남아 있으면 rebase가 막힌다.
    code, _ = _run(["diff", "--quiet"], root)
    code2, _ = _run(["diff", "--cached", "--quiet"], root)
    if code == 1 or code2 == 1:
        _, names = _run(["status", "--short"], root)
        res.error = (
            "기록 외에 커밋하지 않은 변경이 있습니다. "
            "먼저 정리한 뒤 다시 시도하세요.\n" + names
        )
        return res

    had_upstream = _ensure_upstream(res, root, br)

    res.say("원격 변경을 받는 중…")
    code, out = _run(["pull", "--rebase", "origin", br], root)
    if code != 0:
        res.error = out.splitlines()[-1] if out else "pull에 실패했습니다."
        return res

    res.say("올리는 중…")
    args = ["push", "-u", "origin", br] if not had_upstream else ["push", "origin", br]
    code, out = _run(args, root)
    if code != 0:
        res.error = out.splitlines()[-1] if out else "push에 실패했습니다."
        return res

    res.ok = True
    res.say("이미 최신입니다." if "up-to-date" in out.lower() else "원격에 올렸습니다.")
    return res
