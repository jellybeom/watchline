"""KOSPI 일별 장 구분 기록.

날짜 하나에 상태 하나뿐인 작은 데이터라 JSON 파일 한 개로 충분하다.
거래일 기준 연 250행이며, 조회는 날짜 정확 일치 하나뿐이라
딕셔너리로 처리된다.

값은 태그 문자열이 아니라 up/down으로 저장한다. tags.txt에서 태그 이름을
바꿔도 과거 기록이 깨지지 않게 하기 위함이다.

    {
      "2026-08-06": "up",
      "2026-08-07": "down"
    }
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .config import Settings, settings
from .watchlist import Watchlist

UP = "up"
DOWN = "down"
STATES = (UP, DOWN)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class MarketLog:
    """날짜 → 상태. skipped에는 형식이 어긋나 버려진 항목이 담긴다."""

    states: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    def get(self, day: str) -> str | None:
        return self.states.get(day)

    def set(self, day: str, state: str) -> None:
        if not valid_date(day):
            raise ValueError(f"날짜 형식이 올바르지 않습니다: {day}")
        if state not in STATES:
            raise ValueError(f"알 수 없는 상태입니다: {state}")
        self.states[day] = state

    def remove(self, day: str) -> bool:
        return self.states.pop(day, None) is not None

    def items_desc(self) -> list[tuple[str, str]]:
        return sorted(self.states.items(), reverse=True)

    def __len__(self) -> int:
        return len(self.states)


def valid_date(day: str) -> bool:
    if not DATE_RE.match(day or ""):
        return False
    try:
        date.fromisoformat(day)
    except ValueError:
        return False
    return True


def load(path: str | Path | None = None) -> MarketLog:
    """기록을 읽는다. 파일이 없으면 빈 기록을 돌려준다."""
    path = Path(path) if path else settings.kospi_file
    if not path.exists():
        return MarketLog()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path.name}을 읽을 수 없습니다 (JSON 형식 오류): {e}") from e
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name}의 최상위가 객체가 아닙니다.")

    log = MarketLog()
    for day, state in raw.items():
        if valid_date(day) and state in STATES:
            log.states[str(day)] = str(state)
        else:
            log.skipped.append(f"{day}: {state}")
    return log


def save(log: MarketLog, path: str | Path | None = None) -> None:
    """날짜 순으로 정렬해 저장한다. 임시 파일에 쓴 뒤 교체한다."""
    path = Path(path) if path else settings.kospi_file
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(dict(sorted(log.states.items())), ensure_ascii=False, indent=2)
        + "\n"
    )

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def market_closed(now: datetime | None = None, cfg: Settings | None = None) -> bool:
    """당일 판단을 입력해도 되는 시각인지."""
    cfg = cfg or settings
    now = now or datetime.now()
    return now.hour >= cfg.market_close_hour


def apply_market_tags(
    wl: Watchlist, log: MarketLog, tag_order: list[str], cfg: Settings | None = None
) -> dict[str, int]:
    """기준봉 날짜로 KOSPI 태그를 붙인다.

    기존 KOSPI 태그를 먼저 떼고 다시 붙이므로, 기록을 고친 뒤 다시 실행하면
    잘못 붙은 태그가 스스로 교정된다. 다른 태그는 건드리지 않는다.
    """
    cfg = cfg or settings
    by_state = {UP: cfg.tag_market_up, DOWN: cfg.tag_market_down}
    market_tags = set(by_state.values())

    stat = dict(up=0, down=0, no_date=0, no_record=0, cleared=0)

    for row in wl.rows:
        had = [t for t in row.tags if t in market_tags]
        rest = [t for t in row.tags if t not in market_tags]

        state = log.get(row.ref_date) if row.ref_date else None
        if state is None:
            if not row.ref_date:
                stat["no_date"] += 1
            else:
                stat["no_record"] += 1
            if had:
                stat["cleared"] += 1
            row.tags = rest
            continue

        tag = by_state[state]
        stat[state] += 1
        rest.append(tag)
        # 같은 조합이면 항상 같은 문자열이 되도록 설정 순서로 정렬한다.
        row.tags = [t for t in tag_order if t in rest] + [
            t for t in rest if t not in tag_order
        ]

    return stat
