"""수평선 추출 결과를 터미널에 출력한다.

uv run watchline-report
"""

from __future__ import annotations

import sys
from datetime import datetime

from .config import settings
from .hlines import extract, fmt_price

WIDTH = 52


def main() -> None:
    cfg = settings
    res = extract(cfg)
    if res.error:
        sys.exit(f"[중단] {res.error}")

    print(f"계정 폴더: {res.account_dir}\n")
    if res.periods:
        print(
            f"주기 인덱스 분포: {dict(sorted(res.periods.items()))}  (사용: _{cfg.period_index})"
        )
    if len(res.screens) > 1:
        print(f"[주의] 차트 화면이 여러 개입니다: {dict(res.screens)}")

    print()
    print("=" * WIDTH)
    print(f"{'종목코드':<10}{'1선':>11}{'2선':>11}{'3선':>11}{'분포':>9}")
    print("-" * WIDTH)
    for code in sorted(res.lines):
        prices = "".join(f"{fmt_price(p):>11}" for p in res.lines[code])
        print(f"{code:<10}{prices}{res.spreads[code] * 100:>8.1f}%")
    print("=" * WIDTH)

    if res.excluded:
        print(f"\n[경고] 제외 {len(res.excluded)}종목 — 직접 확인이 필요합니다")
        for code, reason in res.excluded.items():
            print(f"  {code}  {reason}")

    if res.notes:
        print(f"\n[참고] {len(res.notes)}건")
        for n in res.notes:
            print(f"  {n}")

    print(
        f"\n정상 {len(res.lines)}종목 / 제외 {len(res.excluded)}종목 / 전체 {res.total}종목"
    )

    if res.types:
        others = {k: v for k, v in res.types.items() if k != cfg.hline_type}
        print(
            f"도구유형: 수평선({cfg.hline_type}) {res.types[cfg.hline_type]}개"
            + (f", 기타 {others}" if others else "")
        )
    if res.mtimes:
        print(
            f"파일시각: {datetime.fromtimestamp(min(res.mtimes)):%Y-%m-%d %H:%M}"
            f" ~ {datetime.fromtimestamp(max(res.mtimes)):%Y-%m-%d %H:%M}"
        )


if __name__ == "__main__":
    main()
