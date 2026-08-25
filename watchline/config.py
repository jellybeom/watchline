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

    # ── HUD 창 ──
    # 1선 기준 가이드선. 위에서 아래 순서로 적는다.
    hud_guides: tuple[float, ...] = (-7.0, -10.0)
    # 스트립 하한 계단. 3선이 한 계단을 넘어가면 다음으로 넓힌다.
    hud_floor_steps: tuple[float, ...] = (-10.0, -15.0, -20.0, -25.0)
    hud_poll_ms: int = 500  # 작도 폴더를 살피는 주기
    hud_settle_ms: int = 300  # 변경 감지 후 읽기까지 기다리는 시간
    hud_retry_ms: int = 300  # 읽기에 실패했을 때 한 번 더 시도하는 간격

    # ── 기록 파일 ──
    kospi_file: Path = PROJECT_ROOT / "kospi.json"  # 날짜별 장 구분
    tag_store_file: Path = PROJECT_ROOT / "stock_tags.json"  # 종목별 태그
    names_file: Path = PROJECT_ROOT / "names.json"  # 종목코드 → 종목명
    tag_market_up: str = "#KOSPI상승장"
    tag_market_down: str = "#KOSPI하락횡보장"
    market_close_hour: int = 20  # 이 시각 이후에 당일 판단을 입력한다
    # ── git 동기화 ──
    project_root: Path = PROJECT_ROOT
    auto_pull: bool = True  # 시작할 때 원격 기록을 내려받는다

    # ── 파일 ──
    tags_file: Path = PROJECT_ROOT / "tags.txt"
    default_csv: Path | None = None  # 실행 시 자동으로 열 CSV


settings = Settings()
