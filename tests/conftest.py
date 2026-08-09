"""테스트용 관심종목 CSV를 코드로 만든다.

영웅문4가 내보낸 실제 파일을 그대로 옮긴 것이다. 별도 파일로 두면
누락되거나 편집기가 인코딩을 바꿔버릴 수 있어 여기에 문자열로 둔다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ENCODING = "cp949"

HEADER = "분,신,종목명,현재가,등락률,L일봉H,거래대금,메모,종목코드"
BLANK = "BLANK|,,,,,,,,"

# 종목 행: 영웅문 내보내기 원본 그대로 (현재가·거래대금에 천 단위 구분,
# 종목코드에 선행 어퍼스트로피)
STOCK_ROWS = [
    '증,,GRT,"3,895",4.42,3840 3895 3625 3895,"1,040",,\'900290',
    '신,,동화기업,"8,060",30,6320 8060 6320 8060,"28,085",2차전지,\'025900',
    '신,,S-Oil,"136,000",8.89,127000 139400 125600 136000,"97,468",,\'010950',
]

# 편집기가 채워 넣는 5개 열. 태그 셀은 값 자체에 큰따옴표를 포함하므로
# CSV로 기록될 때 이중 이스케이프된다.
EXTRA_ROWS = [
    "3355,3215,3105,2026-07-31,",
    '6320,6100,5900,2026-08-07,"""#KOSPI하락횡보장, #상한가, #테마주, #시장을이기는종목"""',
    '127600,123700,120000,2026-08-07,"""#KOSPI하락횡보장, #시장을이기는종목"""',
]

# 입력: 종목 사이사이에 빈 슬롯(BLANK|)이 섞여 있다.
INPUT_LINES = [
    HEADER,
    STOCK_ROWS[0],
    STOCK_ROWS[1],
    BLANK,
    BLANK,
    STOCK_ROWS[2],
    *([BLANK] * 7),
]

OUTPUT_LINES = [
    HEADER + ",1선,2선,3선,기준봉,태그",
    *(f"{s},{e}" for s, e in zip(STOCK_ROWS, EXTRA_ROWS, strict=True)),
]


def _to_bytes(lines: list[str]) -> bytes:
    return ("\r\n".join(lines) + "\r\n").encode(ENCODING)


SAMPLE_INPUT_BYTES = _to_bytes(INPUT_LINES)
SAMPLE_OUTPUT_BYTES = _to_bytes(OUTPUT_LINES)


@pytest.fixture
def sample_input(tmp_path: Path) -> Path:
    """편집 전 원본 관심종목 CSV."""
    p = tmp_path / "sample_input.csv"
    p.write_bytes(SAMPLE_INPUT_BYTES)
    return p


@pytest.fixture
def sample_output(tmp_path: Path) -> Path:
    """5개 열이 채워진 결과 CSV. 형식 비교의 기준이 된다."""
    p = tmp_path / "sample_output.csv"
    p.write_bytes(SAMPLE_OUTPUT_BYTES)
    return p
