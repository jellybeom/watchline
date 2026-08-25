"""HUD가 그릴 내용을 계산한다.

Qt에 의존하지 않는다. 배율 선택, 가이드선 병합, 라벨 간격 조정처럼
눈으로 확인하기 어려운 규칙이 전부 여기 모여 있어야 창을 띄우지 않고
테스트할 수 있다.

좌표계는 백분율이다. 1선이 0%이고 아래로 갈수록 음수이며,
하한(floor)도 음수다. 픽셀 변환은 y_of가 마지막에 한 번만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 하한 배율 계단. 3선이 한 계단을 넘어가면 다음 계단으로 넓힌다.
# 종목마다 배율이 제멋대로 늘어나면 벌어진 정도를 눈으로 비교할 수 없으므로
# 연속으로 늘리지 않고 몇 개의 고정 배율 중에서 고른다.
FLOOR_STEPS: tuple[float, ...] = (-10.0, -15.0, -20.0, -25.0)

# 기본 가이드선.
GUIDES: tuple[float, ...] = (-7.0, -10.0)

KIND_LINE = "line"  # 사용자가 그은 수평선
KIND_GUIDE = "guide"  # 계산으로 만든 기준선

# 가격이 이보다 가까우면 같은 원으로 본다. 가이드선 가격은 실수라
# 정확한 일치를 == 로 판정하면 부동소수 오차에 걸린다.
SAME_WON = 0.5


@dataclass(frozen=True)
class Mark:
    """스트립에 그릴 가로줄 하나."""

    kind: str
    label: str
    price: int
    pct: float
    merged: bool = False  # 수평선과 가이드선의 가격이 같아 한 줄로 합쳐짐

    @property
    def is_line(self) -> bool:
        return self.kind == KIND_LINE


@dataclass(frozen=True)
class View:
    """창 하나가 그릴 전체 상태."""

    code: str
    name: str = ""
    prices: tuple[int, ...] = ()  # 상위 N개, 내림차순
    spread: float | None = None  # 1선 대비 3선. 음수 %
    floor: float = FLOOR_STEPS[0]
    marks: tuple[Mark, ...] = ()
    clamped: bool = False  # 3선이 마지막 계단보다 아래
    warning: str | None = None  # 선 부족 등, 스트립을 그릴 수 없는 사유
    found: tuple[int, ...] = ()  # 부족할 때 실제로 잡힌 선

    @property
    def ok(self) -> bool:
        return self.warning is None

    @property
    def has_name(self) -> bool:
        return bool(self.name)

    @property
    def title(self) -> str:
        """이름을 모르면 코드가 제목 자리를 대신한다."""
        return self.name or self.code

    def gaps(self) -> tuple[float, ...]:
        """이웃한 선 사이의 낙폭. (1↔2, 2↔3, ...)"""
        return tuple(
            pct_of(self.prices[i], self.prices[i + 1])
            for i in range(len(self.prices) - 1)
        )

    def gap_pairs(self) -> tuple[tuple[str, str], ...]:
        """이웃한 선 사이 낙폭을 (라벨, 값) 쌍으로 준다.

        한 덩어리 문자열로 그리면 어디까지가 라벨이고 어디부터가 숫자인지
        구분이 안 된다. 쌍으로 나눠 색과 글꼴을 달리 줄 수 있게 한다.
        """
        return tuple(
            (f"{i + 1}↔{i + 2}", f"{g:.2f}%") for i, g in enumerate(self.gaps())
        )

    def breached(self, guide: float) -> bool:
        """3선이 해당 가이드선 아래(또는 정확히 위)인가."""
        return self.spread is not None and self.spread <= guide


# ────────────────────────────── 계산 ──────────────────────────────


def pct_of(base: float, price: float) -> float:
    """base 대비 price의 등락률(%). base가 0이면 0으로 둔다."""
    if not base:
        return 0.0
    return (price - base) / base * 100.0


def guide_price(base: float, guide: float) -> int:
    """가이드선의 실제 가격. 표시와 병합 판정에 같은 값을 쓴다."""
    return round(base * (1.0 + guide / 100.0))


def choose_floor(
    low: float, steps: tuple[float, ...] = FLOOR_STEPS
) -> tuple[float, bool]:
    """가장 아래 선을 담을 수 있는 첫 계단을 고른다.

    반환: (하한, 마지막 계단으로도 모자란지)
    """
    if not steps:
        raise ValueError("계단이 비어 있습니다")
    for s in steps:
        if low >= s:
            return s, False
    return steps[-1], True


def top_prices(prices, top_n: int = 3) -> tuple[int, ...]:
    """중복을 없애고 위에서부터 top_n개를 고른다."""
    return tuple(sorted({int(p) for p in prices}, reverse=True))[:top_n]


def build_marks(
    top: tuple[int, ...],
    guides: tuple[float, ...] = GUIDES,
    floor: float = FLOOR_STEPS[0],
) -> tuple[Mark, ...]:
    """수평선과 가이드선을 합쳐 위에서 아래 순서로 늘어놓는다.

    가격이 같은 수평선과 가이드선은 한 줄로 합친다. 따로 그리면 선이
    겹치고 같은 숫자가 두 번 찍혀 고장 난 것처럼 보인다.
    """
    if not top:
        return ()
    base = top[0]
    lines = [
        Mark(KIND_LINE, f"{i + 1}선", p, pct_of(base, p)) for i, p in enumerate(top)
    ]

    merged: dict[int, Mark] = {}  # lines 인덱스 → 합쳐진 줄
    guide_marks: list[Mark] = []

    for g in guides:
        if g < floor:  # 배율 밖의 가이드선은 그리지 않는다
            continue
        gp = guide_price(base, g)
        hit = next(
            (
                i
                for i, m in enumerate(lines)
                if i not in merged and abs(m.price - gp) < SAME_WON
            ),
            None,
        )
        if hit is None:
            guide_marks.append(Mark(KIND_GUIDE, f"{g:g}%", gp, g))
        else:
            m = lines[hit]
            merged[hit] = Mark(KIND_LINE, f"{m.label} = {g:g}%", m.price, m.pct, True)

    out = [merged.get(i, m) for i, m in enumerate(lines)] + guide_marks
    return tuple(sorted(out, key=lambda m: (-m.pct, m.kind)))


def build_view(
    code: str,
    prices,
    name: str = "",
    guides: tuple[float, ...] = GUIDES,
    steps: tuple[float, ...] = FLOOR_STEPS,
    top_n: int = 3,
) -> View:
    """수평선 가격 목록에서 창이 그릴 내용을 만든다."""
    uniq = tuple(sorted({int(p) for p in prices}, reverse=True))
    if len(uniq) < top_n:
        return View(
            code=code,
            name=name,
            floor=steps[0],
            warning=f"수평선 {len(uniq)}개 — {top_n}개 필요",
            found=uniq,
        )

    top = uniq[:top_n]
    spread = pct_of(top[0], top[-1])
    floor, clamped = choose_floor(spread, steps)
    return View(
        code=code,
        name=name,
        prices=top,
        spread=spread,
        floor=floor,
        marks=build_marks(top, guides, floor),
        clamped=clamped,
    )


# ────────────────────────────── 배치 ──────────────────────────────


def y_of(pct: float, floor: float, height: float) -> float:
    """등락률을 스트립 안의 y로 옮긴다. 0% → 0, floor → height."""
    if not floor or height <= 0:
        return 0.0
    return max(0.0, min(1.0, pct / floor)) * height


def nudge(ys, min_gap: float, lo: float, hi: float) -> list[float]:
    """라벨이 겹치지 않도록 최소 간격을 확보한다.

    선의 y는 정보이고 라벨은 주석이므로, 선은 그대로 두고 라벨만 민다.
    입력 순서는 유지한 채 값만 바꿔 돌려준다.
    """
    ys = [float(y) for y in ys]
    n = len(ys)
    if n <= 1:
        return ys

    need = (n - 1) * min_gap
    if need > hi - lo:  # 자리가 모자라면 균등 분배가 최선이다
        step = (hi - lo) / (n - 1)
        order = sorted(range(n), key=lambda i: ys[i])
        out = [0.0] * n
        for rank, i in enumerate(order):
            out[i] = lo + step * rank
        return out

    order = sorted(range(n), key=lambda i: ys[i])
    out = list(ys)

    prev = lo - min_gap
    for i in order:  # 위에서 아래로 밀어낸다
        out[i] = prev = max(out[i], prev + min_gap)

    prev = hi + min_gap
    for i in reversed(order):  # 아래로 넘친 만큼 되민다
        out[i] = prev = min(out[i], prev - min_gap)

    return out


def label_ys(
    marks: tuple[Mark, ...],
    floor: float,
    height: float,
    min_gap: float,
    lo: float = 0.0,
    hi: float | None = None,
) -> tuple[list[float], list[float]]:
    """(선의 y, 라벨의 y)를 함께 계산한다."""
    line_ys = [y_of(m.pct, floor, height) for m in marks]
    top = lo
    bottom = height if hi is None else hi
    return line_ys, nudge(line_ys, min_gap, top, bottom)
