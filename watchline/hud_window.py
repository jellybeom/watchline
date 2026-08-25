"""1선 대비 3선 낙폭을 보여주는 상주 창.

작도 폴더를 짧은 주기로 살피다가, 가장 최근 파일이 바뀌면 그 종목의
수평선을 다시 읽어 그린다. 폴더 안의 파일 이름과 시각만 훑으므로
바뀐 것이 없으면 파일을 열지 않는다.

그리기는 전부 paintEvent에 모여 있고, 무엇을 어디에 그릴지는
hud_model이 미리 계산해 둔다.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from . import hud_model as model
from . import hud_source, names
from .config import Settings, settings
from .hlines import find_account_dir

ICON_PATH = Path(__file__).with_name("icon.ico")

# ────────────────────────────── 모양 ──────────────────────────────

C_CARD = QColor("#20242b")
C_EDGE = QColor("#333b47")
C_TEXT = QColor("#dde2e9")
C_DIM = QColor("#8b95a3")
C_LINE = QColor("#c3ccd8")  # 사용자가 그은 수평선
C_WARN = QColor("#f0c674")  # -7% 가이드선
C_DANGER = QColor("#e57373")  # -10% 가이드선
C_MERGE = QColor("#7fd1b9")  # 수평선과 가이드선이 겹친 줄

GUIDE_COLORS = (C_WARN, C_DANGER)

PAD = 16
CARD_W = 320
STRIP_H = 236
HEADER_H = 68  # 종목명 줄 + 낙폭 줄
FOOTER_H = 30  # 구분선 + 이웃 낙폭 줄
WARN_H = 62  # 선이 부족할 때 스트립 대신 쓰는 높이
STRIP_BOTTOM_PAD = 12  # 하한 가이드선이 바닥에 묻히지 않도록 남기는 여백
LABEL_GAP = 18  # 라벨끼리 최소로 벌리는 간격
RADIUS = 10


def _font(size: int, bold: bool = False, mono: bool = False) -> QFont:
    f = QFont("Consolas" if mono else "Segoe UI", size)
    f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return f


def _won(v: float) -> str:
    return f"{int(v):,}"


class HudWindow(QWidget):
    def __init__(self, cfg: Settings | None = None):
        super().__init__()
        self.cfg = cfg or settings
        self.setWindowTitle("3선 간격")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setFixedWidth(CARD_W)

        self.view: model.View | None = None
        self.status = "작도 폴더를 찾는 중…"
        self.stamp: hud_source.Stamp | None = None
        self.updated_at: datetime | None = None
        self.names: dict[str, str] = names.load(self.cfg.names_file)
        self._drag: QPoint | None = None
        self._pending: hud_source.Stamp | None = None
        self._retried = False

        self.account: Path | None = None
        try:
            self.account = find_account_dir(self.cfg)
        except (FileNotFoundError, RuntimeError) as e:
            self.status = str(e)

        self._build_actions()
        self._restore_geometry()
        self._resize_to_content()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        if self.account is not None:
            self.status = "'일' 버튼을 누르면 읽습니다."
            self.timer.start(self.cfg.hud_poll_ms)
            QTimer.singleShot(0, self.poll)

    # ────────────────────────── 창 조작 ──────────────────────────

    def _build_actions(self) -> None:
        close = QAction("닫기", self)
        close.setShortcut(QKeySequence(Qt.Key_Escape))
        close.triggered.connect(self.close)
        self.addAction(close)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos) -> None:
        m = QMenu(self)
        m.addAction("이름 캐시 다시 읽기", self.reload_names)
        m.addSeparator()
        m.addAction("닫기", self.close)
        m.exec(self.mapToGlobal(pos))

    def reload_names(self) -> None:
        self.names = names.load(self.cfg.names_file)
        if self.view is not None:
            self.view = replace(self.view, name=self.names.get(self.view.code, ""))
        self.update()

    def _settings(self) -> QSettings:
        return QSettings("watchline", "hud")

    def _restore_geometry(self) -> None:
        pos = self._settings().value("pos")
        if isinstance(pos, QPoint):
            self.move(pos)

    def closeEvent(self, event):  # noqa: N802
        self._settings().setValue("pos", self.pos())
        super().closeEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag = None

    # ────────────────────────── 갱신 ──────────────────────────

    def poll(self) -> None:
        """폴더를 훑어 바뀐 게 있을 때만 파일을 읽는다."""
        if self.account is None:
            return
        latest = hud_source.find_latest(self.account, self.cfg)
        if latest is None:
            self._set_status("작도 파일이 없습니다.")
            return
        if latest.same_as(self.stamp):
            return
        if latest.same_as(self._pending):
            return
        # 쓰는 도중에 읽으면 반쯤 쓰인 파일을 잡는다. 잠깐 기다렸다 읽는다.
        self._pending = latest
        self._retried = False
        QTimer.singleShot(self.cfg.hud_settle_ms, lambda: self._read(latest))

    def _read(self, stamp: hud_source.Stamp) -> None:
        if self._pending is not stamp and not stamp.same_as(self._pending):
            return  # 기다리는 사이에 더 새로운 파일이 나타났다
        reading = hud_source.read(stamp, self.cfg)
        if reading.error and not self._retried:
            self._retried = True
            QTimer.singleShot(self.cfg.hud_retry_ms, lambda: self._read(stamp))
            return

        self.stamp = stamp
        self._pending = None
        self.updated_at = datetime.fromtimestamp(stamp.mtime)

        if reading.error:
            self.view = model.View(code=stamp.code, warning="작도 파일을 읽지 못함")
            self._set_status(reading.error)
            return

        self.view = model.build_view(
            stamp.code,
            reading.prices,
            name=self.names.get(stamp.code, ""),
            guides=tuple(self.cfg.hud_guides),
            steps=tuple(self.cfg.hud_floor_steps),
            top_n=self.cfg.top_n,
        )
        self.status = ""
        self._resize_to_content()
        self.update()

    def _set_status(self, text: str) -> None:
        if text != self.status:
            self.status = text
            self.update()

    def _resize_to_content(self) -> None:
        ok = self.view is not None and self.view.ok
        body = STRIP_H + STRIP_BOTTOM_PAD if ok else WARN_H
        self.setFixedHeight(PAD + HEADER_H + body + FOOTER_H + PAD)

    # ────────────────────────── 그리기 ──────────────────────────

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        path = QPainterPath()
        path.addRoundedRect(
            0.5, 0.5, self.width() - 1, self.height() - 1, RADIUS, RADIUS
        )
        p.fillPath(path, C_CARD)
        p.strokePath(path, QPen(C_EDGE, 1))

        left, right = PAD, self.width() - PAD
        y = PAD

        v = self.view
        if v is None:
            self._draw_text(p, left, y + 20, self.status or "대기 중", C_DIM, _font(10))
            return

        y = self._draw_header(p, left, right, y, v)
        if v.ok:
            self._draw_strip(p, left, right, y, v)
            y += STRIP_H + STRIP_BOTTOM_PAD
        else:
            y = self._draw_warning(p, left, right, y, v)
        self._draw_footer(p, left, right, self.height() - PAD - 12, v)

    # 각 구획은 다음 구획이 시작할 y를 돌려준다.

    def _draw_header(self, p, left, right, y, v: model.View) -> int:
        p.setFont(_font(11, bold=True))
        p.setPen(C_TEXT)
        p.drawText(
            QRect(left, y, right - left - 60, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            v.title,
        )
        p.setFont(_font(8, mono=True))
        p.setPen(C_DIM)
        p.drawText(
            QRect(left, y, right - left, 18), Qt.AlignRight | Qt.AlignVCenter, v.code
        )
        y += 24

        if v.spread is None:
            p.setFont(_font(14, bold=True))
            p.setPen(C_DIM)
            p.drawText(
                QRect(left, y, right - left, 34), Qt.AlignLeft | Qt.AlignVCenter, "—"
            )
        else:
            p.setFont(_font(19, bold=True, mono=True))
            p.setPen(C_TEXT)
            big = f"{v.spread:.2f}%"
            p.drawText(
                QRect(left, y, right - left, 34), Qt.AlignLeft | Qt.AlignVCenter, big
            )
            scale = self.scale_text(v)
            if scale:
                # 스트립 바닥에 두면 3선이 하한에 붙었을 때 라벨과 겹친다.
                x = left + QFontMetrics(p.font()).horizontalAdvance(big) + 8
                p.setFont(_font(8))
                p.setPen(C_DIM)
                p.drawText(QRect(x, y, 90, 34), Qt.AlignLeft | Qt.AlignVCenter, scale)
            self._draw_badge(p, right, y, v)
        return PAD + HEADER_H

    def _draw_badge(self, p, right, y, v: model.View) -> None:
        guides = tuple(self.cfg.hud_guides)
        hit = [g for g in guides if v.breached(g)]
        if hit:
            worst = min(hit)
            color = GUIDE_COLORS[min(guides.index(worst), len(GUIDE_COLORS) - 1)]
            text = f"{worst:g}% 이탈"
        else:
            color, text = C_DIM, "구간 내"
        if v.clamped:
            color, text = C_DANGER, "범위 밖"

        p.setFont(_font(8))
        w = QFontMetrics(p.font()).horizontalAdvance(text) + 14
        box = QRect(right - w, y + 9, w, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color.red(), color.green(), color.blue(), 40))
        p.drawRoundedRect(box, 4, 4)
        p.setBrush(Qt.NoBrush)
        p.setPen(color)
        p.drawText(box, Qt.AlignCenter, text)

    def _draw_strip(self, p, left, right, top, v: model.View) -> None:
        """가이드선 → 수평선 → 라벨 순서로 그린다.

        한 줄씩 선과 라벨을 번갈아 그리면 나중에 그린 선이 앞선 라벨을
        가로지른다. 층을 나눠 실선이 점선 위에, 라벨이 그 위에 오게 한다.
        """
        marks = v.marks
        if not marks:
            return
        line_ys, label_ys = model.label_ys(marks, v.floor, STRIP_H, LABEL_GAP)
        guides = tuple(self.cfg.hud_guides)
        colors = [self._color_of(m, guides) for m in marks]

        for m, y, color in zip(marks, line_ys, colors, strict=True):
            if m.is_line:
                continue
            pen = QPen(color, 1.0, Qt.DashLine)
            pen.setDashPattern([4, 4])
            p.setPen(pen)
            p.drawLine(left, int(top + y), right, int(top + y))

        for m, y, color in zip(marks, line_ys, colors, strict=True):
            if not m.is_line:
                continue
            p.setPen(QPen(color, 1.4))
            p.drawLine(left, int(top + y), right, int(top + y))

        for m, y, color in zip(marks, label_ys, colors, strict=True):
            self._draw_mark_label(p, left, right, top + y, m, color)

    def scale_text(self, v: model.View) -> str:
        """기본 배율이 아닐 때만 알린다. 늘 띄우면 눈에 안 들어온다."""
        steps = tuple(self.cfg.hud_floor_steps)
        if not steps or v.floor == steps[0]:
            return ""
        return f"배율 {v.floor:g}%"

    def _color_of(self, m: model.Mark, guides) -> QColor:
        if m.merged:
            return C_MERGE
        if m.is_line:
            return C_LINE
        for i, g in enumerate(guides):
            if abs(m.pct - g) < 1e-9:
                return GUIDE_COLORS[min(i, len(GUIDE_COLORS) - 1)]
        return C_WARN

    def _draw_mark_label(self, p, left, right, y, m: model.Mark, color: QColor) -> None:
        """선 위에 라벨을 얹는다. 글자 뒤는 카드색으로 지워 선과 겹치지 않게 한다."""
        top = int(y) - 9
        p.setFont(_font(8))
        fm = QFontMetrics(p.font())
        # 지우는 폭을 글자보다 넉넉히 잡는다. 딱 맞추면 선 끝이 남는다.
        p.fillRect(QRect(left, top, fm.horizontalAdvance(m.label) + 7, 18), C_CARD)
        p.setPen(color if (m.merged or not m.is_line) else C_DIM)
        p.drawText(
            QRect(left, top, right - left, 18), Qt.AlignLeft | Qt.AlignVCenter, m.label
        )

        p.setFont(_font(9, mono=True))
        fm = QFontMetrics(p.font())
        pct_text = "" if m.pct == 0 else f"{m.pct:.2f}"
        price_text = _won(m.price)
        pct_w = fm.horizontalAdvance("-99.99") + 4
        price_w = fm.horizontalAdvance(price_text) + 10

        pct_x = right - pct_w
        price_x = pct_x - price_w
        p.fillRect(QRect(price_x, top, right - price_x + 1, 18), C_CARD)

        p.setPen(color if (m.merged or not m.is_line) else C_TEXT)
        p.drawText(
            QRect(price_x, top, price_w, 18),
            Qt.AlignRight | Qt.AlignVCenter,
            price_text,
        )
        p.setPen(C_DIM)
        p.drawText(
            QRect(pct_x, top, pct_w, 18), Qt.AlignRight | Qt.AlignVCenter, pct_text
        )

    def _draw_warning(self, p, left, right, y, v: model.View) -> int:
        p.setFont(_font(10, bold=True))
        p.setPen(C_WARN)
        p.drawText(
            QRect(left, y, right - left, 20),
            Qt.AlignLeft | Qt.AlignVCenter,
            v.warning or "",
        )
        y += 24
        p.setFont(_font(9, mono=True))
        p.setPen(C_DIM)
        found = " / ".join(_won(x) for x in v.found) or "없음"
        p.drawText(
            QRect(left, y, right - left, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"발견: {found}",
        )
        return y + WARN_H

    def _draw_footer(self, p, left, right, y, v: model.View) -> None:
        p.setPen(QPen(C_EDGE, 1))
        p.drawLine(left, y - 8, right, y - 8)
        p.setFont(_font(8))
        p.setPen(C_DIM)
        gaps = v.gaps()
        if gaps:
            text = "  ".join(f"{i + 1}↔{i + 2} {g:.2f}%" for i, g in enumerate(gaps))
        else:
            text = self.status or ""
        p.drawText(
            QRect(left, y, right - left, 14), Qt.AlignLeft | Qt.AlignVCenter, text
        )
        if self.updated_at:
            p.setFont(_font(8, mono=True))
            p.drawText(
                QRect(left, y, right - left, 14),
                Qt.AlignRight | Qt.AlignVCenter,
                self.updated_at.strftime("%H:%M:%S"),
            )

    def _draw_text(self, p, x, y, text, color, font) -> None:
        p.setFont(font)
        p.setPen(color)
        p.drawText(
            QRect(x, y - 9, self.width() - 2 * x, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            text,
        )


def main() -> None:
    import sys

    app = QApplication(sys.argv)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    win = HudWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
