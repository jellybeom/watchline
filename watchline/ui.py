"""관심종목 편집기 UI."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QObject, QPointF, QRect, Qt
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDateEdit,
    QDialog,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QWidget,
)

from . import hlines, kospi, tagstore, watchlist
from .config import settings
from .conflict_dialog import ConflictDialog
from .kospi_dialog import KospiDialog

# ────────────────────────────── 열 정의 ──────────────────────────────

# 표에 보여줄 원본 열(있는 것만). 나머지 원본 열은 저장 시 그대로 보존된다.
VISIBLE_BASE = ["종목명", "종목코드", "현재가", "등락률", "메모"]

LINE_COLS = ["1선", "2선", "3선"]
SPREAD_COL = "1선↔3선"
DATE_COL = "기준봉"

# 오른쪽 정렬 + 천 단위 구분. 나머지는 모두 가운데 정렬.
RIGHT_COLS = {"현재가", *LINE_COLS}

# 사용자가 값을 넣는 열. 배경을 따로 준다.
EDIT_GROUP = {DATE_COL}

DATE_FORMAT = "yyyy-MM-dd"
RELOAD = "\u21bb"  # 새로고침 기호
ICON_PATH = Path(__file__).with_name("icon.ico")

# CheckStateRole은 정수로 돌아오는데 열거형은 int() 변환을 거부하는 판이 있어
# 값을 미리 꺼내 둔다.
CHECKED = int(Qt.CheckState.Checked.value)

# ────────────────────────────── 색상 ──────────────────────────────

C_WINDOW = "#191c22"
C_BASE = "#20242b"
C_TEXT = "#dde2e9"
C_DIM = "#8b95a3"
C_HEADER = "#2b313b"
C_GRID = "#333b47"
C_ACCENT = "#4a90d9"

ROW_BG = (QColor("#20242b"), QColor("#262c35"))  # 일반 열 (짝/홀)
EDIT_BG = (QColor("#1d2831"), QColor("#23303a"))  # 기준봉·태그 열
WARN_BG = (QColor("#38222a"), QColor("#412833"))  # 경고 행
WARN_FG = QColor("#ff8181")
PENDING_BG = (QColor("#3a3320"), QColor("#443c27"))  # 기록 갱신 예정
PENDING_FG = QColor("#f0c674")

STYLESHEET = f"""
QMainWindow, QWidget {{ background: {C_WINDOW}; color: {C_TEXT}; }}
QToolBar {{
    background: {C_HEADER}; border: 0; border-bottom: 1px solid {C_GRID};
    padding: 2px 4px; spacing: 2px;
}}
QToolBar QToolButton {{ padding: 3px 9px; border-radius: 3px; color: {C_TEXT}; }}
QToolBar QToolButton:hover {{ background: {C_ACCENT}; color: #ffffff; }}
QTableWidget {{
    background: {C_BASE}; gridline-color: {C_GRID};
    selection-background-color: {C_ACCENT}; selection-color: #ffffff;
    outline: 0;
}}
QHeaderView::section {{
    background: {C_HEADER}; color: {C_TEXT};
    padding: 5px 6px; border: 0; border-right: 1px solid {C_GRID};
    border-bottom: 1px solid {C_GRID};
}}
QTableCornerButton::section {{ background: {C_HEADER}; border: 0; }}
QPlainTextEdit {{
    background: #16191e; color: {C_DIM};
    border: 0; border-top: 1px solid {C_GRID}; padding: 4px;
}}
QStatusBar {{
    background: {C_HEADER}; color: {C_DIM};
    border: 0; border-top: 1px solid {C_GRID};
}}
QStatusBar::item {{ border: 0; }}
QStatusBar QLabel {{ background: transparent; color: {C_DIM}; padding: 2px 6px; }}
QMenu {{ background: {C_HEADER}; color: {C_TEXT}; border: 1px solid {C_GRID}; }}
QMenu::item {{ padding: 6px 24px; }}
QMenu::item:selected {{ background: {C_ACCENT}; color: #ffffff; }}
QMenu::item:disabled {{ color: {C_DIM}; }}
QSplitter::handle {{ background: {C_GRID}; height: 2px; }}
"""

OVERLAY_IDLE = f"""
    color: {C_DIM}; font-size: 15px;
    background: rgba(32, 36, 43, 220);
    border: 2px dashed {C_GRID}; border-radius: 8px;
"""

OVERLAY_ACTIVE = f"""
    color: #ffffff; font-size: 17px;
    background: rgba(35, 62, 92, 235);
    border: 2px dashed {C_ACCENT}; border-radius: 8px;
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(C_WINDOW))
    pal.setColor(QPalette.WindowText, QColor(C_TEXT))
    pal.setColor(QPalette.Base, QColor(C_BASE))
    pal.setColor(QPalette.AlternateBase, QColor(C_BASE))
    pal.setColor(QPalette.Text, QColor(C_TEXT))
    pal.setColor(QPalette.Button, QColor(C_HEADER))
    pal.setColor(QPalette.ButtonText, QColor(C_TEXT))
    pal.setColor(QPalette.Highlight, QColor(C_ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor(C_HEADER))
    pal.setColor(QPalette.ToolTipText, QColor(C_TEXT))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)


# ────────────────────────────── 값 표시 ──────────────────────────────


def thousands(text: str) -> str:
    """'127600' → '127,600'. 숫자가 아니면 그대로 둔다."""
    s = str(text).strip().replace(",", "")
    if not s:
        return ""
    try:
        return f"{int(s):,}"
    except ValueError:
        return str(text)


def plain_number(text: str) -> str | None:
    """'127,600' → '127600'. 양의 정수가 아니면 None."""
    s = str(text).strip().replace(",", "")
    if not s:
        return ""
    try:
        v = int(s)
    except ValueError:
        return None
    return str(v) if v > 0 else None


def spread_of(row: watchlist.Row) -> float | None:
    """1선 대비 3선의 낙폭 비율."""
    try:
        p1, p3 = float(row.lines[0]), float(row.lines[2])
    except (ValueError, TypeError):
        return None
    return (p1 - p3) / p1 if p1 > 0 else None


# ────────────────────────────── 위젯 ──────────────────────────────


class DateDelegate(QStyledItemDelegate):
    """셀을 편집하면 달력 팝업이 뜨는 날짜 입력기.

    최솟값을 '비움'으로 쓴다. 화살표를 끝까지 내리면 날짜를 지울 수 있다.
    """

    def createEditor(self, parent, option, index):  # noqa: N802
        ed = QDateEdit(parent)
        ed.setCalendarPopup(True)
        ed.setDisplayFormat(DATE_FORMAT)
        ed.setMinimumDate(QDate(2000, 1, 1))
        ed.setSpecialValueText(" ")
        ed.setKeyboardTracking(False)
        return ed

    def setEditorData(self, editor: QDateEdit, index):  # noqa: N802
        d = QDate.fromString(str(index.data(Qt.EditRole) or ""), DATE_FORMAT)
        editor.setDate(d if d.isValid() else QDate.currentDate())

    def setModelData(self, editor: QDateEdit, model, index):  # noqa: N802
        d = editor.date()
        text = "" if d == editor.minimumDate() else d.toString(DATE_FORMAT)
        model.setData(index, text, Qt.EditRole)


class CheckDelegate(QStyledItemDelegate):
    """태그 열의 체크 표시를 셀 가운데에 직접 그린다.

    기본 위젯의 체크 상자는 왼쪽에 붙고 스타일시트로 칠하면 체크 표시가
    사라지므로, 배경과 상자를 직접 그려 위치와 색을 모두 통제한다.
    """

    BOX = 16

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            bg = index.data(Qt.BackgroundRole)
            if bg is not None:
                painter.fillRect(option.rect, bg)

        box = QRect(0, 0, self.BOX, self.BOX)
        box.moveCenter(option.rect.center())
        state = index.data(Qt.CheckStateRole)
        checked = state is not None and int(state) == CHECKED

        if checked:
            painter.setBrush(QColor(C_ACCENT))
            painter.setPen(QPen(QColor("#9cc7f2"), 1))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(
                QPen(QColor("#ffffff"), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            )
            x, y, w, h = box.x(), box.y(), box.width(), box.height()
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(x + w * 0.24, y + h * 0.52),
                        QPointF(x + w * 0.42, y + h * 0.71),
                        QPointF(x + w * 0.77, y + h * 0.30),
                    ]
                )
            )
        else:
            painter.setBrush(QColor("#12151a"))
            painter.setPen(QPen(QColor("#5a6675"), 1))
            painter.drawRoundedRect(box, 3, 3)

        painter.restore()


class Table(QTableWidget):
    """스페이스바로 태그를 켜고 끌 수 있는 표."""

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Space:
            win = self.window()
            toggled = False
            for idx in self.selectedIndexes():
                if win.is_tag_column(idx.column()):
                    win.toggle_tag(idx.row(), idx.column())
                    toggled = True
            if toggled:
                return
        super().keyPressEvent(event)


# ────────────────────────────── 메인 창 ──────────────────────────────


class MainWindow(QMainWindow):
    def __init__(self, initial: str | None = None):
        super().__init__()
        self.setWindowTitle("관심종목 편집기")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1360, 800)

        self.cfg = settings
        self.data: watchlist.Watchlist | None = None
        self.sources: list[Path] = []  # 합쳐진 입력 파일들
        self.extract: hlines.ExtractResult | None = None
        self.tags: list[str] = watchlist.load_tags(self.cfg.tags_file)
        self.market = kospi.MarketLog()
        self.store = tagstore.TagStore()
        self.market_tag_set = {self.cfg.tag_market_up, self.cfg.tag_market_down}
        self.pending: set[str] = set()  # 기록이 갱신될 예정인 종목
        self.cols: list[str] = []
        self.tag_buffer: list[str] | None = None
        self.dirty = False
        self._loading = False
        self._check_delegate = CheckDelegate(self)

        self._build_ui()
        self.reload_store(quiet=True)
        self.reload_market(quiet=True)
        self.refresh_lines(quiet=True)

        target = initial or (
            str(self.cfg.default_csv) if self.cfg.default_csv else None
        )
        if target:
            self.open_file(target)

    # ────────────────────────── UI 구성 ──────────────────────────

    def _build_ui(self) -> None:
        tb = QToolBar("도구 모음")
        tb.setMovable(False)
        tb.setFloatable(False)
        # 툴바 위에서 우클릭하면 QMainWindow가 표시/숨김 메뉴를 띄우는데,
        # 숨기고 나면 되돌릴 방법이 없다. createPopupMenu에서 함께 막는다.
        tb.setContextMenuPolicy(Qt.PreventContextMenu)
        self.toolbar = tb
        self.addToolBar(tb)

        def act(text, shortcut, slot, tip=""):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setToolTip(f"{tip or text}" + (f" ({shortcut})" if shortcut else ""))
            a.triggered.connect(slot)
            tb.addAction(a)
            return a

        # 파일 조작은 왼쪽
        act("열기", "Ctrl+O", self.on_open)
        act("저장", "Ctrl+S", self.on_save)
        act("초기화", None, self.on_reset, "불러온 목록을 모두 비웁니다")

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # 툴바 배경이 아니라 창 배경이 비치도록 둔다.
        spacer.setAttribute(Qt.WA_NoSystemBackground)
        spacer.setStyleSheet("background: transparent;")
        tb.addWidget(spacer)

        # 새로고침 셋을 붙여 묶고, 성격이 다른 기록 편집은 끝에 둔다.
        act(f"{RELOAD} 3선", "F5", self.on_refresh, "작도 파일에서 3선을 다시 읽습니다")
        act(
            f"{RELOAD} KOSPI",
            "F6",
            self.on_kospi_refresh,
            "kospi.json을 다시 읽어 KOSPI 태그를 붙입니다",
        )
        act(
            f"{RELOAD} 기준봉·태그",
            "F7",
            self.on_tags_refresh,
            "종목별 태그 기록을 다시 대조합니다",
        )
        act("KOSPI 기록", None, self.on_kospi_edit, "날짜별 장 구분을 편집합니다")

        self.table = Table()
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setAlternatingRowColors(False)  # 배경은 직접 칠한다
        self.table.verticalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_context_menu)
        self.table.cellClicked.connect(self.on_cell_clicked)
        self.table.itemChanged.connect(self.on_item_changed)

        # 드롭 안내판. 스크롤바와 머리글을 뺀 뷰포트에 얹어야
        # 오른쪽·아래 모서리가 잘리지 않는다.
        self.overlay = QLabel(self.table.viewport())
        self.overlay.setAlignment(Qt.AlignCenter)
        self.overlay.setWordWrap(True)
        self.overlay.hide()
        self.table.viewport().installEventFilter(self)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setFont(QFont("Consolas", 9))

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.log)
        split.setSizes([600, 170])
        self.setCentralWidget(split)

        self.status = QLabel("파일을 열어주세요.")
        self.statusBar().addWidget(self.status)

        self.setAcceptDrops(True)
        self.update_overlay()

    def createPopupMenu(self):  # noqa: N802
        """툴바 표시/숨김 메뉴를 만들지 않는다.

        기본 메뉴는 툴바를 숨길 수 있는데, 숨기면 그 메뉴를 부를 곳이 사라져
        프로그램을 다시 켜야만 복구된다.
        """
        return None

    OVERLAY_MARGIN = 14

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is self.table.viewport() and event.type() == QEvent.Resize:
            self.place_overlay()
        return super().eventFilter(obj, event)

    def place_overlay(self) -> None:
        m = self.OVERLAY_MARGIN
        self.overlay.setGeometry(self.table.viewport().rect().adjusted(m, m, -m, -m))

    def update_overlay(self, dragging: bool = False, count: int = 1) -> None:
        """파일이 없거나 드래그 중일 때 안내판을 보여준다."""
        if dragging:
            what = f"{count}개 파일" if count > 1 else "파일"
            more = "을 목록에 더합니다" if self.data else "을 엽니다"
            self.overlay.setText(f"여기에 놓으면 {what}{more}")
            self.overlay.setStyleSheet(OVERLAY_ACTIVE)
        elif self.data is None:
            self.overlay.setText(
                "관심종목 CSV 파일을 이곳으로 끌어다 놓으세요\n"
                "여러 개를 놓으면 하나의 목록으로 합쳐집니다\n\n또는 Ctrl+O"
            )
            self.overlay.setStyleSheet(OVERLAY_IDLE)
        else:
            self.overlay.hide()
            return
        self.place_overlay()
        self.overlay.raise_()
        self.overlay.show()

    @staticmethod
    def csv_paths_from_mime(md) -> list[str]:
        """끌어온 것 중 CSV 경로를 순서대로 돌려준다."""
        if md is None or not md.hasUrls():
            return []
        return [
            u.toLocalFile()
            for u in md.urls()
            if u.isLocalFile() and u.toLocalFile().lower().endswith(".csv")
        ]

    def _dropped_csv(self, event) -> list[str]:
        return self.csv_paths_from_mime(event.mimeData())

    def dragEnterEvent(self, event):  # noqa: N802
        paths = self._dropped_csv(event)
        if paths:
            event.acceptProposedAction()
            self.update_overlay(dragging=True, count=len(paths))
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        event.acceptProposedAction() if self._dropped_csv(event) else event.ignore()

    def dragLeaveEvent(self, event):  # noqa: N802
        self.update_overlay()
        event.accept()

    def dropEvent(self, event):  # noqa: N802
        paths = self._dropped_csv(event)
        self.update_overlay()
        if paths:
            event.acceptProposedAction()
            self.open_files(paths)
        else:
            event.ignore()

    def say(self, msg: str) -> None:
        self.log.appendPlainText(msg)

    def update_status(self, suffix: str = "") -> None:
        if not self.data:
            return
        missing = sum(1 for r in self.data.rows if not r.has_lines)
        nodate = sum(1 for r in self.data.rows if not r.ref_date)
        over = sum(
            1
            for r in self.data.rows
            if (s := spread_of(r)) is not None and s >= self.cfg.spread_limit
        )
        parts = [
            f"{len(self.data.rows)}종목",
            f"1~3선 미확보 {missing}",
            f"분포 {self.cfg.spread_limit * 100:.0f}% 초과 {over}",
            f"기준봉 미입력 {nodate}",
        ]
        if self.pending:
            parts.append(f"기록 갱신 예정 {len(self.pending)}")
        self.status.setText("  |  ".join(parts) + suffix)

    # ───────────────────────── 수평선 추출 ─────────────────────────

    def refresh_lines(self, quiet: bool = False) -> None:
        self.extract = hlines.extract(self.cfg)
        r = self.extract
        if r.error:
            self.say(f"[수평선] 읽기 실패 — {r.error}")
            return
        self.say(f"[수평선] 정상 {len(r.lines)}종목 / 제외 {len(r.excluded)}종목")
        if not quiet:
            for code, why in list(r.excluded.items())[:30]:
                self.say(f"    {code}  {why}")

    def on_refresh(self) -> None:
        self.refresh_lines()
        if self.data and self.extract:
            self.apply_lines()
            self.apply_market_tags(quiet=True)
            self.populate()

    def apply_lines(self) -> None:
        """열려 있는 모든 파일에 3선을 반영한다."""
        if not self.extract:
            return
        if not self.data:
            return
        s = watchlist.apply_lines(self.data, self.extract.lines)
        self.say(
            f"[적용] 갱신 {s['filled']} / 기존유지 {s['kept']} "
            f"/ 미확보 {s['blank']}"
        )

    # ─────────────────────────── 파일 ───────────────────────────

    def on_open(self) -> None:
        """새 목록으로 연다. 여러 개를 고르면 하나로 이어붙인다."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "관심종목 CSV 열기", "", "CSV 파일 (*.csv);;모든 파일 (*)"
        )
        if paths:
            self.open_files(paths, append=False)

    def open_files(self, paths: list[str], append: bool = True) -> None:
        """파일들을 읽어 하나의 목록으로 합친다.

        입력이 몇 개든 결과는 파일 하나이므로, 행을 이어붙이고
        종목코드가 겹치면 먼저 들어온 쪽을 남긴다.
        """
        if not paths:
            return
        if not append and self.data and not self.confirm_discard():
            return
        if not append:
            self.data = None
            self.sources = []

        for path in paths:
            self.load_into(path)

        if not self.data:
            return
        self.apply_lines()
        self.apply_tag_store()  # 기준봉 확정 + 태그 복원 + KOSPI 태그
        self.populate()
        self.refresh_title()
        self.update_overlay()

    def load_into(self, path: str) -> bool:
        """파일 하나를 읽어 현재 목록에 더한다."""
        target = Path(path).resolve()
        if any(p.resolve() == target for p in self.sources):
            self.say(f"[열기] 이미 불러온 파일입니다 — {target.name}")
            return False

        try:
            data = watchlist.load(path)
        except Exception as e:
            QMessageBox.critical(
                self, "열기 실패", f"{Path(path).name}\n\n{type(e).__name__}: {e}"
            )
            return False

        self.say(f"\n[열기] {data.path}")
        self.say(
            f"       종목 {len(data.rows)}개, 제외된 행 {len(data.dropped)}개"
            + ("  (기존 입력값 유지)" if data.had_extra_cols else "")
        )
        for lineno, why in data.dropped[:20]:
            self.say(f"    줄 {lineno}: {why}")
        if len(data.dropped) > 20:
            self.say(f"    … 외 {len(data.dropped) - 20}건")

        if self.data is None:
            self.data = data
        else:
            st = watchlist.append_watchlist(self.data, data)
            self.say(
                f"       이어붙임 {st['added']}종목"
                + (f", 중복 {st['duplicate']}종목 건너뜀" if st["duplicate"] else "")
            )
            if st["dup_codes"]:
                codes = ", ".join(st["dup_codes"][:10])
                self.say(
                    f"       중복 종목코드 — {codes}"
                    + (" …" if len(st["dup_codes"]) > 10 else "")
                )
            if st["col_diff"]:
                self.say(
                    f"       [주의] 열 구성이 다릅니다 — {', '.join(st['col_diff'])}"
                )
            self.dirty = True

        self.sources.append(Path(path))
        return True

    def on_reset(self) -> None:
        """처음 실행한 상태로 되돌린다. 기록 파일은 건드리지 않는다."""
        if self.data and not self.confirm_discard():
            return
        self.data = None
        self.sources = []
        self.pending = set()
        self.dirty = False
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.cols = []
        self.log.clear()
        self.status.setText("파일을 열어주세요.")
        self.refresh_title()
        self.update_overlay()
        self.reload_store(quiet=True)
        self.reload_market(quiet=True)

    def refresh_title(self) -> None:
        if not self.sources:
            self.setWindowTitle("관심종목 편집기")
            return
        name = self.sources[0].name
        if len(self.sources) > 1:
            name += f" 외 {len(self.sources) - 1}개"
        self.setWindowTitle(f"관심종목 편집기 — {name}{' *' if self.dirty else ''}")

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        return (
            QMessageBox.question(
                self,
                "저장하지 않은 변경",
                "저장하지 않은 변경이 있습니다. 새로 열까요?",
            )
            == QMessageBox.Yes
        )

    # ───────────────────────── 종목별 태그 기록 ─────────────────────────

    def reload_store(self, quiet: bool = False) -> None:
        try:
            self.store = tagstore.load(self.cfg.tag_store_file)
        except ValueError as e:
            self.store = tagstore.TagStore()
            self.say(f"[태그기록] {e}")
            if not quiet:
                QMessageBox.critical(self, "태그 기록", str(e))
            return
        if not quiet:
            self.say(f"[태그기록] {len(self.store)}종목")
        for bad in self.store.skipped:
            self.say(f"    형식 오류로 건너뜀 — {bad}")

    def apply_tag_store(self, ask: bool = True) -> None:
        """기록과 대조해 기준봉·태그를 정한다. 기준봉 확정이 먼저다."""
        if not self.data:
            return

        decisions = tagstore.judge(self.data, self.store)
        conflicts = [d for d in decisions if d.needs_prompt]

        choices: dict[str, bool] = {}
        if conflicts and ask:
            dlg = ConflictDialog(conflicts, self)
            if dlg.exec() == QDialog.Accepted:
                choices = dlg.choices()
            else:
                self.say(
                    f"[태그기록] 기준봉 확인을 취소했습니다 "
                    f"— {len(conflicts)}종목은 기록된 날짜를 유지합니다."
                )

        st = tagstore.apply_decisions(self.data, decisions, choices, self.cfg)
        self.pending = {
            d.code for d in decisions if d.verdict is tagstore.Verdict.NEWER
        }
        for code, keep in choices.items():
            if not keep:
                self.pending.add(code)

        self.say(
            f"[태그기록] 기록 일치 {st['same']} / 새 종목 {st['new']} "
            f"/ 기준봉 갱신 {st['newer']} / 확인 필요 {st['older']} "
            f"/ 기준봉 없음 {st['no_date']}"
        )
        if self.pending:
            self.say(f"       저장 시 기록이 갱신될 종목 {len(self.pending)}개")

        # 기준봉이 확정된 뒤에 KOSPI 태그를 붙인다.
        self.apply_market_tags(quiet=True)

    def on_tags_refresh(self) -> None:
        if not self.data:
            return
        self.reload_store()
        self.apply_tag_store()
        self.populate()
        self.dirty = True
        self.refresh_title()

    # ───────────────────────── KOSPI 장 기록 ─────────────────────────

    def reload_market(self, quiet: bool = False) -> None:
        """kospi.json을 다시 읽는다."""
        try:
            self.market = kospi.load(self.cfg.kospi_file)
        except ValueError as e:
            self.market = kospi.MarketLog()
            self.say(f"[KOSPI] {e}")
            if not quiet:
                QMessageBox.critical(self, "KOSPI 기록", str(e))
            return
        if not quiet:
            self.say(f"[KOSPI] {len(self.market)}일 기록")
        for bad in self.market.skipped:
            self.say(f"    형식 오류로 건너뜀 — {bad}")

    def apply_market_tags(self, quiet: bool = False) -> dict | None:
        """기준봉 날짜로 KOSPI 태그를 다시 붙인다."""
        if not self.data:
            return None
        s = kospi.apply_market_tags(self.data, self.market, self.tags, self.cfg)
        if not quiet:
            self.say(
                f"[KOSPI] 상승장 {s['up']} / 하락횡보장 {s['down']} "
                f"/ 기준봉 없음 {s['no_date']} / 기록 없음 {s['no_record']}"
            )
            if s["cleared"]:
                self.say(f"       기록이 없어 태그를 뗀 종목 {s['cleared']}개")
        return s

    def on_kospi_edit(self) -> None:
        dlg = KospiDialog(self.market, self.cfg, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            kospi.save(dlg.log, self.cfg.kospi_file)
        except OSError as e:
            QMessageBox.critical(self, "저장 실패", f"{type(e).__name__}: {e}")
            return
        self.market = dlg.log
        self.say(
            f"\n[KOSPI] 기록 저장 — {len(self.market)}일 " f"({self.cfg.kospi_file})"
        )
        self.on_kospi_refresh(reload_file=False)

    def on_kospi_refresh(self, reload_file: bool = True) -> None:
        if reload_file:
            self.reload_market()
        if not self.data:
            return
        s = self.apply_market_tags()
        self.populate()
        if s and (s["up"] or s["down"] or s["cleared"]):
            self.dirty = True
            self.refresh_title()
        self.update_status("  *수정됨" if self.dirty else "")

    def on_save(self) -> None:
        """항상 저장 위치를 묻는다. 같은 이름을 고르면 덮어쓴다."""
        if not self.data:
            return
        empty = [r.name or r.code for r in self.data.rows if not r.ref_date]
        if empty:
            preview = ", ".join(empty[:8]) + (" …" if len(empty) > 8 else "")
            if (
                QMessageBox.question(
                    self,
                    "기준봉 미입력",
                    f"기준봉이 비어 있는 종목이 {len(empty)}개 있습니다.\n{preview}\n\n"
                    "그대로 저장할까요?",
                )
                != QMessageBox.Yes
            ):
                return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "다른 이름으로 저장",
            str(self.data.path),
            "CSV 파일 (*.csv);;모든 파일 (*)",
        )
        if not path:
            return

        try:
            saved = watchlist.save(self.data, path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "저장 실패",
                f"대상 파일은 그대로입니다.\n\n{type(e).__name__}: {e}",
            )
            return

        st = tagstore.update_from(self.data, self.store, self.cfg)
        try:
            tagstore.save(self.store, self.cfg.tag_store_file)
        except OSError as e:
            QMessageBox.warning(
                self,
                "태그 기록 저장 실패",
                f"CSV는 저장되었습니다.\n\n{type(e).__name__}: {e}",
            )
        else:
            self.say(
                f"[태그기록] {st['written']}종목 갱신"
                + (
                    f", 기준봉 없어 건너뜀 {st['skipped_no_date']}종목"
                    if st["skipped_no_date"]
                    else ""
                )
            )
            self.pending = set()

        self.say(f"[저장] {saved}  ({len(self.data.rows)}종목)")
        self.sources = [saved]
        self.dirty = False
        self.refresh_title()
        self.update_status()

    def closeEvent(self, event):  # noqa: N802
        if (
            self.dirty
            and QMessageBox.question(
                self,
                "저장하지 않은 변경",
                "저장하지 않은 변경이 있습니다. 그대로 닫을까요?",
            )
            != QMessageBox.Yes
        ):
            event.ignore()
            return
        event.accept()

    # ─────────────────────────── 표 그리기 ───────────────────────────

    def is_tag_column(self, col: int) -> bool:
        """사용자가 직접 켜고 끌 수 있는 태그 열인지."""
        return (
            0 <= col < len(self.cols)
            and self.cols[col] in self.tags
            and self.cols[col] not in self.market_tag_set
        )

    def _bg(self, col: str, row_idx: int, warn: bool) -> QColor:
        parity = row_idx % 2
        if warn:
            return WARN_BG[parity]
        if col in EDIT_GROUP or col in self.tags:
            return EDIT_BG[parity]
        return ROW_BG[parity]

    def populate(self) -> None:
        if not self.data:
            return
        self._loading = True
        try:
            base = [c for c in VISIBLE_BASE if c in self.data.header]
            self.cols = base + LINE_COLS + [SPREAD_COL, DATE_COL] + self.tags

            t = self.table
            t.clear()
            t.setColumnCount(len(self.cols))
            t.setRowCount(len(self.data.rows))
            t.setHorizontalHeaderLabels(self.cols)
            t.setItemDelegateForColumn(self.cols.index(DATE_COL), DateDelegate(t))
            for tag in self.tags:
                t.setItemDelegateForColumn(self.cols.index(tag), self._check_delegate)

            for r, row in enumerate(self.data.rows):
                for c, col in enumerate(self.cols):
                    t.setItem(r, c, self._make_item(row, col, r))

            hh = t.horizontalHeader()
            hh.setSectionResizeMode(QHeaderView.ResizeToContents)
            for name, width in ((DATE_COL, 110), (SPREAD_COL, 84)):
                i = self.cols.index(name)
                hh.setSectionResizeMode(i, QHeaderView.Fixed)
                t.setColumnWidth(i, width)

            self.update_status()
        finally:
            self._loading = False

    def _make_item(self, row: watchlist.Row, col: str, r: int) -> QTableWidgetItem:
        missing = not row.has_lines
        it = QTableWidgetItem()
        warn = False

        if col in LINE_COLS:
            it.setText(thousands(row.lines[LINE_COLS.index(col)]))
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            warn = missing
            if missing and self.extract:
                it.setToolTip(
                    self.extract.excluded.get(row.code)
                    or "작도 파일에 수평선 정보가 없습니다."
                )
        elif col == SPREAD_COL:
            s = spread_of(row)
            it.setText("" if s is None else f"{s * 100:.1f}%")
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if s is not None and s >= self.cfg.spread_limit:
                warn = True
                it.setForeground(QBrush(WARN_FG))
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                it.setToolTip(
                    f"1선 대비 3선이 {s * 100:.1f}% 낮습니다. "
                    f"불필요한 수평선이 섞였는지 확인하세요."
                )
        elif col == DATE_COL:
            it.setText(row.ref_date)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            if row.code in self.pending:
                it.setBackground(QBrush(PENDING_BG[r % 2]))
                it.setForeground(QBrush(PENDING_FG))
                it.setToolTip("저장하면 이 기준봉으로 태그 기록이 갱신됩니다.")
                return it
        elif col in self.tags:
            # 체크 표시는 셀 아무 곳이나 클릭해서 바꾼다(on_cell_clicked).
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it.setCheckState(Qt.Checked if col in row.tags else Qt.Unchecked)
            if col in self.market_tag_set:
                # 기준봉과 kospi.json에서 자동으로 정해지므로 손으로 못 바꾼다.
                it.setToolTip(
                    "KOSPI 태그는 기준봉과 'KOSPI 기록'에서 자동으로 정해집니다."
                )
                it.setForeground(QBrush(QColor(C_DIM)))
        elif col == "종목코드":
            it.setText(row.code)  # 선행 어퍼스트로피는 감춘다
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        else:
            it.setText(row.base.get(col, ""))
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

        align = Qt.AlignRight if col in RIGHT_COLS else Qt.AlignCenter
        it.setTextAlignment(align | Qt.AlignVCenter)
        it.setBackground(QBrush(self._bg(col, r, warn)))
        return it

    def _repaint_row(self, r: int) -> None:
        """1~3선을 고친 뒤 낙폭과 배경을 다시 계산한다."""
        if not self.data:
            return
        row = self.data.rows[r]
        self._loading = True
        try:
            for name in (*LINE_COLS, SPREAD_COL):
                c = self.cols.index(name)
                self.table.setItem(r, c, self._make_item(row, name, r))
        finally:
            self._loading = False

    # ─────────────────────────── 편집 ───────────────────────────

    def on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or not self.data:
            return
        r = item.row()
        row = self.data.rows[r]
        col = self.cols[item.column()]

        if col == DATE_COL:
            row.ref_date = item.text().strip()
            self.sync_market_tag(r)
        elif col in LINE_COLS:
            value = plain_number(item.text())
            if value is None:
                QMessageBox.warning(self, "값 오류", "가격은 양의 정수로 입력하세요.")
                self._repaint_row(r)
                return
            row.lines[LINE_COLS.index(col)] = value
            self._repaint_row(r)
        else:
            return

        self.dirty = True
        self.update_status("  *수정됨")

    def sync_market_tag(self, r: int) -> None:
        """기준봉을 손으로 고쳤을 때 그 행만 다시 맞춘다.

        KOSPI 태그는 날짜에서 따라오므로 다시 계산하지만, 태그 기록은
        다시 조회하지 않는다. 조회하면 방금 체크한 태그가 기록된 값으로
        되돌아가 버린다. 기록 대조는 '기준봉·태그 새로고침'에서만 한다.
        """
        if not self.data or not self.cols:
            return
        row = self.data.rows[r]
        one = watchlist.Watchlist(self.data.path, self.data.header, [row], [], True)
        kospi.apply_market_tags(one, self.market, self.tags, self.cfg)

        entry = self.store.get(row.code)
        if row.ref_date and (entry is None or entry.date != row.ref_date):
            self.pending.add(row.code)
        else:
            self.pending.discard(row.code)

        self._loading = True
        try:
            for tag in self.tags:
                self.table.item(r, self.cols.index(tag)).setCheckState(
                    Qt.Checked if tag in row.tags else Qt.Unchecked
                )
            self.table.setItem(
                r, self.cols.index(DATE_COL), self._make_item(row, DATE_COL, r)
            )
        finally:
            self._loading = False

    def on_cell_clicked(self, r: int, c: int) -> None:
        """태그 열은 체크박스가 아니라 셀 어디를 눌러도 켜지고 꺼진다."""
        if self.is_tag_column(c):
            self.toggle_tag(r, c)

    def toggle_tag(self, r: int, c: int) -> None:
        if not self.data:
            return
        row = self.data.rows[r]
        tag = self.cols[c]
        if tag in row.tags:
            row.tags.remove(tag)
        else:
            row.tags.append(tag)
        # 같은 조합이면 항상 같은 문자열이 되도록 설정 파일 순서로 정렬한다.
        row.tags = [t for t in self.tags if t in row.tags]

        self._loading = True
        try:
            self.table.item(r, c).setCheckState(
                Qt.Checked if tag in row.tags else Qt.Unchecked
            )
        finally:
            self._loading = False

        self.dirty = True
        self.update_status("  *수정됨")

    # ─────────────────────────── 우클릭 메뉴 ───────────────────────────

    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def on_context_menu(self, pos) -> None:
        if not self.data:
            return
        idx = self.table.indexAt(pos)
        if idx.isValid() and idx not in self.table.selectedIndexes():
            self.table.setCurrentCell(idx.row(), idx.column())

        rows = self.selected_rows()
        if rows:
            menu = self.build_context_menu(rows)
            menu.exec(self.table.viewport().mapToGlobal(pos))

    def build_context_menu(self, rows: list[int]) -> QMenu:
        """선택 상태에 맞는 우클릭 메뉴를 만든다."""
        menu = QMenu(self)
        n = len(rows)
        suffix = f" ({n}개 행)" if n > 1 else ""

        menu.addAction(f"기준봉 오늘로{suffix}", lambda: self.set_today(rows))

        clear = menu.addAction(f"기준봉 삭제{suffix}", lambda: self.clear_date(rows))
        clear.setEnabled(any(self.data.rows[r].ref_date for r in rows))

        menu.addSeparator()

        if n == 1:
            tags = self.data.rows[rows[0]].tags
            label = f"태그 복사 — {', '.join(tags)}" if tags else "태그 복사 — (없음)"
            menu.addAction(label, lambda: self.copy_tags(rows[0]))
        else:
            menu.addAction("태그 복사").setEnabled(False)

        if self.tag_buffer is None:
            menu.addAction("태그 붙여넣기").setEnabled(False)
        else:
            shown = ", ".join(self.tag_buffer) or "(없음)"
            menu.addAction(
                f"태그 붙여넣기{suffix} — {shown}", lambda: self.paste_tags(rows)
            )
        return menu

    def set_today(self, rows: list[int]) -> None:
        today = QDate.currentDate().toString(DATE_FORMAT)
        self._set_dates(rows, today)

    def clear_date(self, rows: list[int]) -> None:
        self._set_dates(rows, "")

    def _set_dates(self, rows: list[int], text: str) -> None:
        c = self.cols.index(DATE_COL)
        for r in rows:
            self.table.item(r, c).setText(text)  # itemChanged가 값과 태그를 반영한다

    def copy_tags(self, r: int) -> None:
        # KOSPI 태그는 기준봉에서 따라오므로 복사 대상에서 뺀다.
        # 함께 옮기면 붙여넣은 종목의 기준봉과 어긋난다.
        self.tag_buffer = [
            t for t in self.data.rows[r].tags if t not in self.market_tag_set
        ]
        name = self.data.rows[r].name or self.data.rows[r].code
        self.say(f"[태그] 복사 — {name}: {', '.join(self.tag_buffer) or '(없음)'}")

    def paste_tags(self, rows: list[int]) -> None:
        if self.tag_buffer is None:
            return
        for r in rows:
            row = self.data.rows[r]
            keep = [t for t in row.tags if t in self.market_tag_set]
            row.tags = [t for t in self.tags if t in self.tag_buffer or t in keep]
            self._loading = True
            try:
                for tag in self.tags:
                    self.table.item(r, self.cols.index(tag)).setCheckState(
                        Qt.Checked if tag in row.tags else Qt.Unchecked
                    )
            finally:
                self._loading = False
        self.dirty = True
        self.update_status("  *수정됨")
        self.say(
            f"[태그] {len(rows)}개 행에 붙여넣기 — "
            f"{', '.join(self.tag_buffer) or '(없음)'}"
        )


def main() -> None:
    app = QApplication(sys.argv)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    apply_theme(app)
    win = MainWindow(sys.argv[1] if len(sys.argv) > 1 else None)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
