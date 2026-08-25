"""가장 최근에 저장된 작도 파일 하나를 골라 읽는다.

영웅문4는 주기 버튼('일'/'주' 등)을 누를 때 지금 보고 있는 종목의 작도
파일만 다시 쓴다. 따라서 계정 폴더에서 mtime이 가장 최근인 .cs5가
곧 화면에 떠 있는 종목이고, 별도의 종목 선택 장치가 필요 없다.

hlines.extract()는 폴더 전체를 파싱하므로 주기적으로 부르기에는 무겁다.
여기서는 후보를 고를 때 파일을 열지 않고, 실제로 바뀐 한 개만 읽는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import Settings, settings
from .hlines import FILENAME_RE, read_drawing_file


@dataclass(frozen=True)
class Stamp:
    """파일을 열지 않고 알 수 있는 정보. 변경 감지에 쓴다."""

    path: Path
    code: str
    mtime: float
    size: int

    def same_as(self, other: Stamp | None) -> bool:
        return (
            other is not None
            and self.path == other.path
            and self.mtime == other.mtime
            and self.size == other.size
        )


@dataclass(frozen=True)
class Reading:
    """작도 파일 하나를 읽은 결과."""

    stamp: Stamp
    prices: tuple[int, ...] = ()  # 수평선 가격, 내림차순
    error: str | None = None


def find_latest(acct: Path, cfg: Settings | None = None) -> Stamp | None:
    """계정 폴더에서 조건에 맞는 가장 최근 작도 파일을 고른다.

    scandir은 디렉터리 항목에서 종류와 시각을 함께 받아오므로
    파일 수백 개를 훑어도 부담이 없다.
    """
    cfg = cfg or settings
    latest: Stamp | None = None
    try:
        it = os.scandir(acct)
    except OSError:
        return None

    with it:
        for entry in it:
            try:
                if not entry.is_file():
                    continue
                m = FILENAME_RE.match(entry.name)
                if not m or m["period"] != cfg.period_index:
                    continue
                if cfg.screen_prefix is not None and m["screen"] != cfg.screen_prefix:
                    continue
                st = entry.stat()
            except OSError:
                continue  # 훑는 도중 사라진 파일은 건너뛴다
            if latest is None or st.st_mtime > latest.mtime:
                # 코드는 대문자로 통일한다. HTS가 소문자로 저장해도 짝이 맞도록.
                latest = Stamp(
                    Path(entry.path), m["code"].upper(), st.st_mtime, st.st_size
                )
    return latest


def read(stamp: Stamp, cfg: Settings | None = None) -> Reading:
    """작도 파일에서 수평선 가격만 뽑는다. 다른 작도는 무시한다."""
    cfg = cfg or settings
    info = read_drawing_file(stamp.path, cfg)
    prices = tuple(sorted({int(p) for p in info["prices"]}, reverse=True))
    if not prices and info["warnings"]:
        return Reading(stamp, (), "; ".join(info["warnings"][:3]))
    return Reading(stamp, prices)
