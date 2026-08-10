"""KOSPI 장 구분 기록 편집 창."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from . import kospi
from .config import Settings

DATE_FORMAT = "yyyy-MM-dd"


class KospiDialog(QDialog):
    """날짜별 상승장/하락횡보장을 추가·수정·삭제한다.

    창을 닫을 때까지는 사본만 고치므로, 취소하면 원본이 그대로 남는다.
    """

    def __init__(self, log: kospi.MarketLog, cfg: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KOSPI 장 기록")
        self.resize(420, 520)

        self.cfg = cfg
        self.log = kospi.MarketLog(states=dict(log.states))  # 사본
        self.labels = {
            kospi.UP: cfg.tag_market_up.lstrip("#"),
            kospi.DOWN: cfg.tag_market_down.lstrip("#"),
        }

        self._build()
        self.reload_table()
        self.on_date_changed()

    # ────────────────────────── 구성 ──────────────────────────

    def _build(self) -> None:
        root = QVBoxLayout(self)

        entry = QHBoxLayout()
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat(DATE_FORMAT)
        self.date.setDate(QDate.currentDate())
        self.date.dateChanged.connect(self.on_date_changed)

        self.state = QComboBox()
        for key in (kospi.UP, kospi.DOWN):
            self.state.addItem(self.labels[key], key)

        self.btn_set = QPushButton("추가 / 수정")
        self.btn_set.clicked.connect(self.on_set)

        entry.addWidget(self.date, 1)
        entry.addWidget(self.state, 1)
        entry.addWidget(self.btn_set)
        root.addLayout(entry)

        self.note = QLabel()
        self.note.setWordWrap(True)
        root.addWidget(self.note)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["날짜", "장 구분"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.on_row_selected)
        root.addWidget(self.table, 1)

        self.btn_del = QPushButton("선택 삭제")
        self.btn_del.clicked.connect(self.on_delete)
        root.addWidget(self.btn_del)

        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("저장")
        box.button(QDialogButtonBox.Cancel).setText("취소")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    # ────────────────────────── 동작 ──────────────────────────

    def current_date(self) -> str:
        return self.date.date().toString(DATE_FORMAT)

    def on_date_changed(self) -> None:
        """이미 기록된 날짜면 그 값을 띄우고, 장 마감 전이면 알려준다."""
        day = self.current_date()
        existing = self.log.get(day)
        if existing:
            self.state.setCurrentIndex(self.state.findData(existing))
            self.btn_set.setText("수정")
        else:
            self.btn_set.setText("추가")

        msgs = []
        if existing:
            msgs.append(f"이미 '{self.labels[existing]}'으로 기록된 날짜입니다.")
        if self.date.date() == QDate.currentDate() and not kospi.market_closed(
            cfg=self.cfg
        ):
            msgs.append(
                f"아직 장 마감 전입니다. "
                f"{self.cfg.market_close_hour}시 이후 입력을 권합니다."
            )
        self.note.setText("  ".join(msgs))

    def on_set(self) -> None:
        self.log.set(self.current_date(), self.state.currentData())
        self.reload_table()
        self.on_date_changed()

    def on_delete(self) -> None:
        days = self.selected_days()
        if not days:
            return
        if (
            QMessageBox.question(
                self,
                "삭제 확인",
                f"{len(days)}건을 삭제할까요?\n\n"
                + ", ".join(days[:8])
                + (" …" if len(days) > 8 else ""),
            )
            != QMessageBox.Yes
        ):
            return
        for day in days:
            self.log.remove(day)
        self.reload_table()
        self.on_date_changed()

    def selected_days(self) -> list[str]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.table.item(r, 0).text() for r in rows]

    def on_row_selected(self) -> None:
        days = self.selected_days()
        if len(days) == 1:
            self.date.setDate(QDate.fromString(days[0], DATE_FORMAT))

    def reload_table(self) -> None:
        items = self.log.items_desc()
        self.table.setRowCount(len(items))
        for r, (day, state) in enumerate(items):
            d = QTableWidgetItem(day)
            v = QTableWidgetItem(self.labels[state])
            for it in (d, v):
                it.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 0, d)
            self.table.setItem(r, 1, v)
        self.setWindowTitle(f"KOSPI 장 기록 — {len(items)}일")
