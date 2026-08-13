"""기준봉 충돌 확인 창.

입력 파일의 기준봉이 기록보다 과거인 종목들을 한 화면에 모아,
어느 날짜가 맞는지 한 번에 고르게 한다. 종목마다 창을 띄우면
수십 번 눌러야 하므로 목록형으로 둔다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .tagstore import Decision

KEEP = "기록된 날짜"
USE_FILE = "입력 파일 날짜"


class ConflictDialog(QDialog):
    """반환값은 종목코드 → 기록을 쓸지 여부."""

    def __init__(self, decisions: list[Decision], parent=None):
        super().__init__(parent)
        self.setWindowTitle("기준봉 확인")
        self.resize(720, 460)
        self.decisions = decisions
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)

        head = QLabel(
            f"입력 파일의 기준봉이 기록보다 과거인 종목이 {len(self.decisions)}개 있습니다.\n"
            "어느 날짜가 맞는지 골라주세요. "
            f"'{KEEP}'를 고르면 그때 저장한 태그도 함께 불러옵니다."
        )
        head.setWordWrap(True)
        root.addWidget(head)

        bulk = QHBoxLayout()
        for text, value in ((f"모두 {KEEP}로", True), (f"모두 {USE_FILE}로", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, v=value: self.set_all(v))
            bulk.addWidget(b)
        bulk.addStretch(1)
        root.addLayout(bulk)

        cols = ["종목", "기록된 날짜", "입력 파일", "기록된 태그", "선택"]
        self.table = QTableWidget(len(self.decisions), len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)

        self.pickers: list[QComboBox] = []
        for r, d in enumerate(self.decisions):
            cells = [
                d.name or d.code,
                d.stored_date,
                d.file_date,
                ", ".join(d.stored_tags) or "(없음)",
            ]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c != 3:
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, it)

            box = QComboBox()
            box.addItem(KEEP, True)
            box.addItem(USE_FILE, False)
            self.table.setCellWidget(r, 4, box)
            self.pickers.append(box)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("적용")
        box.button(QDialogButtonBox.Cancel).setText("취소")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    def set_all(self, keep: bool) -> None:
        for box in self.pickers:
            box.setCurrentIndex(0 if keep else 1)

    def choices(self) -> dict[str, bool]:
        return {
            d.code: box.currentData()
            for d, box in zip(self.decisions, self.pickers, strict=True)
        }
