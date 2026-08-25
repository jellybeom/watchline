"""영웅문4 작도 파일(.cs5)에서 일봉 수평선 가격을 추출한다.

작도 데이터는 서버가 아닌 로컬 파일에만 있으며, CP949 INI 형식이다.
섹션 하나가 작도 객체 하나이고, 수평선은 `분석도구유형=20`,
가격은 `시작값` 필드에 들어 있다(`종료값`/`추가값`은 내부 잔여값이라 쓰지 않는다).

영웅문4는 주기 전환 시점이나 HTS 종료 시에만 디스크에 기록하므로,
읽기 전에 HTS를 종료하는 것이 가장 안전하다.
"""

from __future__ import annotations

import configparser
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Settings, settings

FILENAME_RE = re.compile(
    r"^(?P<screen>.+?)\$dr@(?P<code>[0-9A-Za-z]{6})_(?P<period>\d+)\.cs5$"
)

ENCODING = "cp949"


@dataclass
class ExtractResult:
    """추출 결과. lines에 담긴 종목만 사용 가능하고, excluded는 수동 확인 대상이다."""

    lines: dict[str, tuple[float, ...]] = field(default_factory=dict)
    spreads: dict[str, float] = field(default_factory=dict)  # (1선-3선)/1선
    excluded: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    types: Counter = field(default_factory=Counter)
    periods: Counter = field(default_factory=Counter)
    screens: Counter = field(default_factory=Counter)
    mtimes: list[float] = field(default_factory=list)
    account_dir: Path | None = None
    error: str | None = None

    @property
    def total(self) -> int:
        return len(self.lines) + len(self.excluded)


def find_account_dir(cfg: Settings) -> Path:
    """계정 폴더(#XXXX$)를 찾는다."""
    if cfg.hero_account_dir is not None:
        if not cfg.hero_account_dir.is_dir():
            raise FileNotFoundError(f"계정 폴더가 없습니다: {cfg.hero_account_dir}")
        return cfg.hero_account_dir

    if not cfg.hero_user_root.is_dir():
        raise FileNotFoundError(f"user 폴더가 없습니다: {cfg.hero_user_root}")

    cands = [
        d for d in cfg.hero_user_root.iterdir() if d.is_dir() and d.name.startswith("#")
    ]
    if not cands:
        raise FileNotFoundError(f"계정 폴더를 찾지 못했습니다: {cfg.hero_user_root}")
    if len(cands) > 1:
        names = ", ".join(d.name for d in cands)
        raise RuntimeError(
            f"계정 폴더가 여러 개입니다. HERO_ACCOUNT_DIR을 지정하세요: {names}"
        )
    return cands[0]


def load_ini(path: Path) -> configparser.ConfigParser:
    """CP949 INI를 관대하게 읽는다(중복 섹션 허용, 키 대소문자 보존)."""
    text = path.read_bytes().decode(ENCODING, errors="replace")
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read_string(text)
    return cp


def parse_price(raw: str, tolerance: float) -> tuple[float | None, str | None]:
    """가격 문자열을 파싱한다. 정수가 아니면 소수점을 버리고 내림한다.

    반환: (값, 경고사유)
    """
    s = raw.strip().replace(",", "")
    if not s:
        return None, "빈 값"
    try:
        v = float(s)
    except ValueError:
        return None, f"숫자 아님({s})"
    if v <= 0:
        return None, f"0 이하({s})"
    floored = float(math.floor(v))
    if abs(v - floored) > tolerance:
        return floored, f"소수점 내림({s} → {floored:.0f})"
    return floored, None


def read_drawing_file(path: Path, cfg: Settings) -> dict:
    """작도 파일 하나에서 수평선 가격 목록을 뽑는다."""
    out: dict = {"prices": [], "types": Counter(), "warnings": []}
    try:
        cp = load_ini(path)
    except (configparser.Error, OSError) as e:
        out["warnings"].append(f"파일 읽기 실패: {type(e).__name__}: {e}")
        return out

    for section in cp.sections():
        d = cp[section]
        tool = d.get("분석도구유형", "").strip()
        out["types"][tool] += 1
        if tool != cfg.hline_type:
            continue
        raw = d.get("시작값")
        if raw is None:
            out["warnings"].append(f"[{section}] 시작값 필드 없음")
            continue
        price, warn = parse_price(raw, cfg.price_tolerance)
        if warn:
            out["warnings"].append(f"[{section}] {warn}")
        if price is not None:
            out["prices"].append(price)
    return out


def fmt_price(v: float) -> str:
    """터미널 표시용. 자릿수 구분 기호를 넣는다."""
    return f"{int(v):,}" if v == int(v) else f"{v:,.1f}"


def extract(cfg: Settings | None = None) -> ExtractResult:
    """설정된 계정 폴더 전체를 훑어 종목별 상위 N개 수평선을 반환한다."""
    cfg = cfg or settings
    res = ExtractResult()

    try:
        acct = find_account_dir(cfg)
    except (FileNotFoundError, RuntimeError) as e:
        res.error = str(e)
        return res
    res.account_dir = acct

    by_code: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    # scandir은 디렉터리 항목에서 종류와 시각을 함께 받아오므로
    # iterdir + is_file + stat 조합보다 파일당 시스템 호출이 적다.
    for entry in os.scandir(acct):
        if not entry.is_file():
            continue
        m = FILENAME_RE.match(entry.name)
        if not m:
            continue
        res.periods[m["period"]] += 1
        if m["period"] != cfg.period_index:
            continue
        screen = m["screen"]
        res.screens[screen] += 1
        if cfg.screen_prefix is not None and screen != cfg.screen_prefix:
            continue
        # 코드는 대문자로 통일한다. HTS가 소문자로 저장해도 짝이 맞도록.
        by_code[m["code"].upper()].append((screen, Path(entry.path)))

    if not by_code:
        res.error = "조건에 맞는 작도 파일이 없습니다. PERIOD_INDEX를 확인하세요."
        return res

    now = datetime.now().timestamp()

    for code in sorted(by_code):
        entries = by_code[code]

        # 같은 종목이 여러 차트 화면에 있으면 어느 쪽이 맞는지 알 수 없다.
        if len(entries) > 1:
            screens = ", ".join(s for s, _ in entries)
            res.excluded[code] = f"여러 화면에 작도 존재 ({screens})"
            continue

        _, path = entries[0]
        # stat 결과는 아래 stale 계산에서도 쓰므로 한 번만 부른다.
        mtime = path.stat().st_mtime
        res.mtimes.append(mtime)

        info = read_drawing_file(path, cfg)
        res.types.update(info["types"])
        res.notes.extend(f"{code}  {w}" for w in info["warnings"])

        prices = sorted(set(info["prices"]), reverse=True)
        dup = len(info["prices"]) - len(prices)

        if len(prices) < cfg.top_n:
            found = " / ".join(fmt_price(p) for p in prices) or "없음"
            res.excluded[code] = f"수평선 {len(prices)}개뿐 (발견: {found})"
            continue

        top = tuple(prices[: cfg.top_n])
        spread = (top[0] - top[-1]) / top[0]

        # 의도치 않은 고가 수평선이 섞이면 1선이 밀려 올라가 낙폭이 커진다.
        # 제외하지 않고 통과시키되, 확인이 필요하다고 표시한다.
        if spread >= cfg.spread_limit:
            res.notes.append(
                f"{code}  가격분포 {spread * 100:.1f}% "
                f"(한계 {cfg.spread_limit * 100:.0f}%) — 확인 필요"
            )

        if dup:
            res.notes.append(f"{code}  동일 가격 수평선 {dup}개 제거")
        if len(prices) > cfg.top_n:
            rest = len(prices) - cfg.top_n
            res.notes.append(f"{code}  수평선 {len(prices)}개 중 하위 {rest}개 제외")
        stale = (now - mtime) / 86400
        if stale > cfg.stale_days:
            res.notes.append(f"{code}  작도 파일이 {stale:.0f}일 전 것")

        res.lines[code] = top
        res.spreads[code] = spread

    return res
