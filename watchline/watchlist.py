"""영웅문4 관심종목 CSV 읽기/쓰기.

인코딩은 CP949 고정이며, 종목코드가 유효한 행만 남기고
나머지(BLANK| 등 빈 슬롯, 중복 행)는 버린다.
저장은 원본 덮어쓰기이므로 백업을 먼저 남기고 원자적으로 교체한다.

태그 셀은 값 자체에 따옴표를 포함한다(예: 큰따옴표로 감싼 #A, #B).
CSV로 기록될 때 따옴표가 이중으로 이스케이프되어
외부 프로그램이 쓰는 기존 형식과 일치한다.
"""

from __future__ import annotations

import csv
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings

ENCODING = "cp949"
EXTRA_COLS = ["1선", "2선", "3선", "기준봉", "태그"]
CODE_COL = "종목코드"

CODE_RE = re.compile(r"^[0-9A-Za-z]{6}$")
TAG_SEP = ", "

DEFAULT_TAGS = [
    "#KOSPI상승장",
    "#KOSPI하락횡보장",
    "#시장을이기는종목",
    "#상한가",
    "#테마주",
    "#섹터주",
]


@dataclass
class Row:
    """관심종목 한 줄."""

    base: dict[str, str]  # 원본 열 값(추가 5열 제외)
    code: str  # 정규화된 6자리 코드
    code_raw: str  # 원본 표기('900290 등)
    lines: list[str] = field(default_factory=lambda: ["", "", ""])
    ref_date: str = ""  # 기준봉 (YYYY-MM-DD)
    tags: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.base.get("종목명", "")

    @property
    def has_lines(self) -> bool:
        return all(self.lines)


@dataclass
class Watchlist:
    path: Path
    header: list[str]  # 원본 열 순서(추가 5열 제외)
    rows: list[Row]
    dropped: list[tuple[int, str]]  # (원본 줄번호, 사유)
    had_extra_cols: bool


# ──────────────────────────── 값 변환 ────────────────────────────


def normalize_code(raw: str) -> str:
    """선행 어퍼스트로피를 떼고 대문자로 통일한다. 예: 0015N0"""
    return raw.strip().lstrip("'").strip().upper()


def parse_tags(cell: str) -> list[str]:
    """따옴표로 감싼 태그 셀을 목록으로 되돌린다."""
    s = cell.strip()
    if not s:
        return []
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return [t.strip() for t in s.split(",") if t.strip()]


def format_tags(tags: list[str]) -> str:
    """태그 목록을 따옴표로 감싼 셀 값으로 만든다. 비었으면 빈 문자열."""
    return '"' + TAG_SEP.join(tags) + '"' if tags else ""


def format_price(v: float | str | None) -> str:
    """CSV용 가격 표기. 자릿수 구분 기호를 넣지 않는다."""
    if v is None or v == "":
        return ""
    f = float(v)
    return str(int(f)) if f == int(f) else f"{f:g}"


# ────────────────────────────── 읽기 ──────────────────────────────


def load(path: str | Path) -> Watchlist:
    """관심종목 CSV를 읽는다. 이미 5개 열이 붙어 있으면 기존 입력값을 보존한다."""
    path = Path(path)
    raw = path.read_bytes().decode(ENCODING, errors="replace")
    reader = csv.reader(raw.splitlines())

    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        raise ValueError("빈 파일입니다.") from None

    if CODE_COL not in header:
        raise ValueError(f"'{CODE_COL}' 열을 찾을 수 없습니다. 열 목록: {header}")

    had_extra = all(c in header for c in EXTRA_COLS)
    base_header = [h for h in header if h not in EXTRA_COLS]

    rows: list[Row] = []
    dropped: list[tuple[int, str]] = []
    seen: dict[str, int] = {}

    for lineno, rec in enumerate(reader, start=2):
        if not any(c.strip() for c in rec):
            dropped.append((lineno, "빈 행"))
            continue

        d = dict(zip(header, rec, strict=False))
        code = normalize_code(d.get(CODE_COL, ""))

        if not CODE_RE.match(code):
            label = (d.get("종목명") or (rec[0] if rec else "")).strip()
            dropped.append(
                (lineno, f"종목코드 없음/형식 오류 ({label or '내용 없음'})")
            )
            continue

        if code in seen:
            dropped.append((lineno, f"{code} 중복 (줄 {seen[code]}과 동일)"))
            continue
        seen[code] = lineno

        row = Row(
            base={k: d.get(k, "") for k in base_header},
            code=code,
            code_raw=d.get(CODE_COL, "").strip(),
        )
        if had_extra:
            row.lines = [d.get(c, "").strip() for c in ("1선", "2선", "3선")]
            row.ref_date = d.get("기준봉", "").strip()
            row.tags = parse_tags(d.get("태그", ""))

        rows.append(row)

    return Watchlist(path, base_header, rows, dropped, had_extra)


# ────────────────────────────── 쓰기 ──────────────────────────────


def save(wl: Watchlist, path: str | Path | None = None) -> Path:
    """지정한 경로에 저장한다. 경로를 주지 않으면 현재 경로에 쓴다.

    임시 파일에 먼저 쓰고 교체하므로, 실패해도 대상 파일이 손상되지 않고
    다른 프로그램이 반쯤 쓰인 파일을 읽는 일도 없다.
    """
    path = Path(path) if path else wl.path

    records = [wl.header + EXTRA_COLS]
    code_at = wl.header.index(CODE_COL)
    for r in wl.rows:
        rec = [r.base.get(c, "") for c in wl.header]
        rec[code_at] = r.code_raw
        rec += [*r.lines, r.ref_date, format_tags(r.tags)]
        records.append(rec)

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding=ENCODING, errors="replace") as f:
            csv.writer(f).writerows(records)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    wl.path = path
    return path


# ────────────────────────── 태그 목록 설정 ─────────────────────────


def load_tags(path: str | Path | None = None) -> list[str]:
    """태그 목록을 읽는다. 파일이 없으면 기본값으로 새로 만든다."""
    path = Path(path) if path else settings.tags_file
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(DEFAULT_TAGS) + "\n", encoding="utf-8")
        return list(DEFAULT_TAGS)

    tags, seen = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("#!") or t in seen:
            continue
        seen.add(t)
        tags.append(t)
    return tags or list(DEFAULT_TAGS)


def merge_metadata(
    target: Watchlist, source: Watchlist, *, overwrite: bool = False
) -> dict[str, int]:
    """이전 파일의 기준봉·태그만 현재 파일로 옮긴다.

    종목코드로 짝을 맞추며, 가격·메모 등 원본 열과 1~3선은 절대 건드리지 않는다.
    overwrite가 False면 현재 값이 비어 있는 항목만 채운다.
    """
    src = {r.code: r for r in source.rows}
    stat = dict(
        matched=0, date_filled=0, tags_filled=0, date_kept=0, tags_kept=0, unmatched=0
    )

    for row in target.rows:
        other = src.get(row.code)
        if other is None:
            stat["unmatched"] += 1
            continue
        stat["matched"] += 1

        if other.ref_date:
            if row.ref_date and not overwrite:
                stat["date_kept"] += 1
            elif other.ref_date != row.ref_date:
                row.ref_date = other.ref_date
                stat["date_filled"] += 1

        if other.tags:
            if row.tags and not overwrite:
                stat["tags_kept"] += 1
            elif other.tags != row.tags:
                row.tags = list(other.tags)
                stat["tags_filled"] += 1

    return stat


def apply_lines(
    wl: Watchlist, extracted: dict[str, tuple[float, ...]]
) -> dict[str, int]:
    """추출 결과를 행에 채운다. 값이 없는 종목은 기존 값을 지우지 않는다."""
    stat = {"filled": 0, "kept": 0, "blank": 0}
    for row in wl.rows:
        top = extracted.get(row.code)
        if top:
            row.lines = [format_price(p) for p in top]
            stat["filled"] += 1
        elif any(row.lines):
            stat["kept"] += 1
        else:
            row.lines = ["", "", ""]
            stat["blank"] += 1
    return stat
