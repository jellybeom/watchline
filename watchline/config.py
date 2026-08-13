"""설정.

값을 바꾸려면 아래 기본값을 직접 수정하면 된다.
테스트나 다른 경로로 돌릴 때는 Settings 인스턴스를 만들어 함수에 넘긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    # ── 영웅문4 경로 ──
    # user 폴더. 설치 경로에 맞게 수정한다.
    hero_user_root: Path = Path(r"C:\KiwoomHero4\user")
    # 계정 폴더(#XXXX$). None이면 자동 탐지하고, 여러 개면 오류로 알려준다.
    hero_account_dir: Path | None = None
    # 차트 화면번호 프리픽스(예: "660000_2").
    # None이면 전체를 보되, 한 종목이 여러 화면에 걸치면 제외하고 경고한다.
    screen_prefix: str | None = None

    # ── 수평선 판정 ──
    hline_type: str = "20"  # 분석도구유형 코드. 20 = 수평선
    period_index: str = "0"  # 파일명 끝의 _N. 0 = 일봉
    top_n: int = 3  # 뽑아낼 선 개수
    spread_limit: float = 0.10  # 1선 대비 3선 낙폭 한계. 통상 6~8%
    price_tolerance: float = 0.01  # 가격이 정수에서 이만큼 벗어나면 경고
    stale_days: int = 30  # 작도 파일이 이보다 오래되면 참고 메모

    # ── 기록 파일 ──
    kospi_file: Path = PROJECT_ROOT / "kospi.json"  # 날짜별 장 구분
    tag_store_file: Path = PROJECT_ROOT / "stock_tags.json"  # 종목별 태그
    tag_market_up: str = "#KOSPI상승장"
    tag_market_down: str = "#KOSPI하락횡보장"
    market_close_hour: int = 20  # 이 시각 이후에 당일 판단을 입력한다
    # 기록 파일이 이 일수보다 오래되면 git pull을 잊었는지 알려준다.
    # 여러 PC에서 번갈아 쓸 때 옛 기록으로 덮어쓰는 사고를 막는다.
    stale_record_days: int = 3

    # ── 파일 ──
    tags_file: Path = PROJECT_ROOT / "tags.txt"
    default_csv: Path | None = None  # 실행 시 자동으로 열 CSV


settings = Settings()
