"""종목별 태그 기록.

종목 하나에 `{"date": ..., "tags": [...]}` 하나만 둔다. 즉 가장 최근에
저장한 기준봉과 그때의 태그만 남으며, 다시 저장하면 덮어쓴다.

    {
      "005930": {"date": "2026-08-12", "tags": ["#시장을이기는종목", "#상한가"]},
      "000660": {"date": "2026-08-13", "tags": []}
    }

KOSPI 태그(#KOSPI상승장 / #KOSPI하락횡보장)는 여기에 넣지 않는다.
그 정보는 kospi.json이 날짜별로 갖고 있으므로, 기준봉만 알면 언제든
다시 만들 수 있고 종목별로 중복 저장하면 어긋날 여지가 생긴다.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .config import Settings, settings
from .kospi import valid_date
from .watchlist import Watchlist


class Verdict(Enum):
    """입력 파일의 기준봉과 기록을 견준 결과."""

    NEW = "new"  # 기록에 없는 종목 → 태그 해제 상태로 시작
    SAME = "same"  # 날짜가 같음 → 기록된 태그를 가져온다
    NEWER = "newer"  # 입력이 더 최신 → 태그 해제, 갱신 예정 표시
    OLDER = "older"  # 입력이 더 과거 → 사용자에게 물어본다
    NO_DATE = "no_date"  # 기준봉 없음 → 태그 해제 상태로 표시


@dataclass
class Entry:
    date: str
    tags: list[str] = field(default_factory=list)


@dataclass
class TagStore:
    entries: dict[str, Entry] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    def get(self, code: str) -> Entry | None:
        return self.entries.get(code)

    def put(self, code: str, day: str, tags: list[str]) -> None:
        self.entries[code] = Entry(day, list(tags))

    def __len__(self) -> int:
        return len(self.entries)


@dataclass
class Decision:
    """종목 하나에 대한 판정 결과."""

    code: str
    name: str
    verdict: Verdict
    file_date: str  # 입력 파일의 기준봉
    stored_date: str = ""  # 기록된 기준봉
    stored_tags: list[str] = field(default_factory=list)

    @property
    def needs_prompt(self) -> bool:
        return self.verdict is Verdict.OLDER


# ────────────────────────────── 저장/읽기 ──────────────────────────────


def load(path: str | Path | None = None) -> TagStore:
    """기록을 읽는다. 파일이 없으면 빈 기록을 돌려준다."""
    path = Path(path) if path else settings.tag_store_file
    if not path.exists():
        return TagStore()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path.name}을 읽을 수 없습니다 (JSON 형식 오류): {e}") from e
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name}의 최상위가 객체가 아닙니다.")

    store = TagStore()
    for code, item in raw.items():
        day = item.get("date", "") if isinstance(item, dict) else None
        tags = item.get("tags", []) if isinstance(item, dict) else None
        if not isinstance(tags, list) or not valid_date(day or ""):
            store.skipped.append(f"{code}: {item}")
            continue
        store.entries[str(code).upper()] = Entry(day, [str(t) for t in tags])
    return store


def save(store: TagStore, path: str | Path | None = None) -> Path:
    """종목코드 순으로 정렬해 저장한다. 임시 파일에 쓴 뒤 교체한다."""
    path = Path(path) if path else settings.tag_store_file
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        code: {"date": e.date, "tags": e.tags}
        for code, e in sorted(store.entries.items())
    }
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


# ────────────────────────────── 판정/적용 ──────────────────────────────


def market_tags(cfg: Settings | None = None) -> set[str]:
    cfg = cfg or settings
    return {cfg.tag_market_up, cfg.tag_market_down}


def judge(wl: Watchlist, store: TagStore) -> list[Decision]:
    """각 종목의 기준봉을 기록과 견준다. 아무것도 바꾸지 않는다."""
    out: list[Decision] = []
    for row in wl.rows:
        entry = store.get(row.code)
        if not row.ref_date:
            v = Verdict.NO_DATE
        elif entry is None:
            v = Verdict.NEW
        elif entry.date == row.ref_date:
            v = Verdict.SAME
        elif row.ref_date > entry.date:
            v = Verdict.NEWER
        else:
            v = Verdict.OLDER
        out.append(
            Decision(
                code=row.code,
                name=row.name,
                verdict=v,
                file_date=row.ref_date,
                stored_date=entry.date if entry else "",
                stored_tags=list(entry.tags) if entry else [],
            )
        )
    return out


def apply_decisions(
    wl: Watchlist,
    decisions: list[Decision],
    keep_stored: dict[str, bool] | None = None,
    cfg: Settings | None = None,
) -> dict[str, int]:
    """판정 결과를 행에 반영한다.

    keep_stored는 OLDER 종목에 대한 사용자의 선택이다. True면 기록된
    기준봉과 태그를 쓰고, False면 입력 파일의 기준봉을 쓰고 태그를 비운다.
    선택이 없으면 안전한 쪽인 기록 유지로 본다.

    KOSPI 태그는 여기서 다루지 않는다. 기준봉이 확정된 뒤에
    kospi.apply_market_tags()가 따로 붙인다.
    """
    cfg = cfg or settings
    keep_stored = keep_stored or {}
    mkt = market_tags(cfg)
    by_code = {d.code: d for d in decisions}
    stat = dict.fromkeys(("new", "same", "newer", "older", "no_date", "pending"), 0)

    for row in wl.rows:
        d = by_code.get(row.code)
        if d is None:
            continue

        keep_market = [t for t in row.tags if t in mkt]

        if d.verdict is Verdict.SAME:
            row.tags = list(d.stored_tags)
            stat["same"] += 1
        elif d.verdict is Verdict.OLDER:
            if keep_stored.get(row.code, True):
                row.ref_date = d.stored_date
                row.tags = list(d.stored_tags)
            else:
                row.ref_date = d.file_date
                row.tags = []
            stat["older"] += 1
            if row.code not in keep_stored:
                stat["pending"] += 1
        else:  # NEW / NEWER / NO_DATE
            row.tags = []
            stat[d.verdict.value] += 1

        row.tags = [t for t in row.tags if t not in mkt] + keep_market
        row.tags = order_tags(row.tags, cfg)

    return stat


def order_tags(
    tags: list[str], cfg: Settings | None = None, tag_order: list[str] | None = None
) -> list[str]:
    """같은 조합이면 항상 같은 문자열이 되도록 정렬한다."""
    if tag_order is None:
        from .watchlist import load_tags

        tag_order = load_tags((cfg or settings).tags_file)
    known = [t for t in tag_order if t in tags]
    return known + [t for t in tags if t not in tag_order]


def update_from(
    wl: Watchlist, store: TagStore, cfg: Settings | None = None
) -> dict[str, int]:
    """현재 목록의 기준봉·태그로 기록을 덮어쓴다.

    기준봉이 없는 종목은 날짜를 특정할 수 없으므로 건드리지 않는다.
    KOSPI 태그는 저장하지 않는다.
    """
    cfg = cfg or settings
    mkt = market_tags(cfg)
    stat = dict(written=0, skipped_no_date=0)

    for row in wl.rows:
        if not row.ref_date:
            stat["skipped_no_date"] += 1
            continue
        store.put(row.code, row.ref_date, [t for t in row.tags if t not in mkt])
        stat["written"] += 1
    return stat
