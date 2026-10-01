from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QDate, QDateTime, QTime, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QComboBox,
    QDateTimeEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from client.api.base import ApiClient
from client.ui.widgets.api_task import TaskRunner


class OptionalDateTimeEdit(QDateTimeEdit):
    """日期时间编辑器，使用破折号表示空值。"""

    NULL_DATETIME = QDateTime(QDate(2000, 1, 1), QTime(0, 0))

    def __init__(self, value: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.setMinimumDateTime(self.NULL_DATETIME)
        self.setSpecialValueText("—")
        self.set_value(value)

    def set_value(self, value: str | None) -> None:
        parsed = _parse_datetime(value)
        self.setDateTime(parsed if parsed.isValid() else self.NULL_DATETIME)

    def value(self) -> str | None:
        if self.dateTime() == self.NULL_DATETIME:
            return None
        return self.dateTime().toString("yyyy-MM-dd HH:mm")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.dateTime() == self.NULL_DATETIME:
            self.setDateTime(QDateTime.currentDateTime())
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace}:
            self.setDateTime(self.NULL_DATETIME)
            event.accept()
            return
        super().keyPressEvent(event)


class SummaryCard(QFrame):
    clicked = Signal(str)

    def __init__(self, filter_value: str, parent=None) -> None:
        super().__init__(parent)
        self.filter_value = filter_value
        self.setObjectName("SummaryCard")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.filter_value)
        super().mouseReleaseEvent(event)


class DashboardPage(QWidget):
    event_message = Signal(str)

    STATUS_OPTIONS = ["已投递", "简历筛选中", "笔试中", "待面试", "一面", "二面", "三面", "HR面", "Offer", "已结束"]
    SUMMARY_CARDS = [
        ("全部投递", "全部"),
        ("已投递", "已投递"),
        ("待面试", "待面试"),
        ("Offer", "Offer"),
    ]

    MARKER_COLUMN = 0
    COMPANY_COLUMN = 1
    POSITION_COLUMN = 2
    BASE_COLUMN = 3
    STATUS_COLUMN = 4
    INTERVIEW_TIME_COLUMN = 5
    UPDATED_AT_COLUMN = 6
    DEFAULT_PAGE_SIZE = 10

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.runner = TaskRunner(api, self)
        self.runner.failed.connect(self._integration_error)
        self.runner.idle.connect(self._integration_ready)
        self._email_task_id = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._poll_email)
        self._loading = False
        self._active_filter = "全部"
        self.current_page = 1
        self.page_size = self.DEFAULT_PAGE_SIZE
        self.total_pages = 1
        self.total_records = 0
        self._original_records: dict[int, dict] = {}
        self._dirty_ids: set[int] = set()
        self._build_ui()
        self.refresh()

    @property
    def has_pending_changes(self) -> bool:
        return bool(self._dirty_ids)

    def _build_ui(self) -> None:
        self.setObjectName("PageSurface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        header = QHBoxLayout()
        heading_box = QVBoxLayout()
        title = QLabel("当前投递进度")
        title.setObjectName("PageTitle")
        subtitle = QLabel("表格内容可直接编辑，修改后的行会显示 * 标记")
        subtitle.setObjectName("PageSubtitle")
        heading_box.addWidget(title)
        heading_box.addWidget(subtitle)

        email_button = self.email_button = QPushButton("扫描未读邮件")
        email_button.setObjectName("SecondaryButton")
        email_button.clicked.connect(self._sync_email)
        feishu_button = self.feishu_button = QPushButton("同步飞书")
        feishu_button.setObjectName("PrimaryButton")
        feishu_button.clicked.connect(self._sync_feishu)

        header.addLayout(heading_box)
        header.addStretch()
        header.addWidget(email_button)
        header.addWidget(feishu_button)
        layout.addLayout(header)
        self.integration_notice = QLabel()
        self.integration_notice.setWordWrap(True)
        self.integration_notice.setObjectName("MutedLabel")
        layout.addWidget(self.integration_notice)

        self.cards = QHBoxLayout()
        layout.addLayout(self.cards)

        toolbar = QFrame()
        toolbar.setObjectName("Toolbar")
        controls = QHBoxLayout(toolbar)
        controls.setContentsMargins(12, 9, 12, 9)
        self.filter_combo = QComboBox()
        self.filter_combo.setObjectName("StatusFilter")
        self.filter_combo.addItems(["全部", *self.STATUS_OPTIONS])
        _color_status_items(self.filter_combo)
        _apply_status_tone(self.filter_combo, "全部")
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        self.save_button = QPushButton("保存修改")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_changes)
        controls.addWidget(QLabel("筛选状态"))
        controls.addWidget(self.filter_combo)
        controls.addStretch()
        pending_hint = QLabel("* 表示该行尚未保存")
        pending_hint.setObjectName("MutedLabel")
        self.save_feedback = QLabel("")
        self.save_feedback.setObjectName("SaveFeedback")
        self.save_feedback.hide()
        controls.addWidget(self.save_feedback)
        controls.addWidget(pending_hint)
        controls.addWidget(self.save_button)
        layout.addWidget(toolbar)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["", "公司", "岗位", "Base", "当前状态", "面试时间", "更新时间"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.itemChanged.connect(self._on_item_changed)
        header_view = self.table.horizontalHeader()
        header_view.setSectionsMovable(False)
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        for column, width in {
            self.MARKER_COLUMN: 20,
            self.COMPANY_COLUMN: 135,
            self.POSITION_COLUMN: 220,
            self.BASE_COLUMN: 100,
            self.STATUS_COLUMN: 150,
            self.INTERVIEW_TIME_COLUMN: 190,
            self.UPDATED_AT_COLUMN: 190,
        }.items():
            header_view.resizeSection(column, width)
        layout.addWidget(self.table, 1)

        pagination = QHBoxLayout()
        pagination.addStretch()
        self.previous_button = QPushButton("上一页")
        self.previous_button.setObjectName("SecondaryButton")
        self.previous_button.clicked.connect(lambda: self._change_page(-1))
        self.page_label = QLabel("第 1 / 1 页")
        self.page_label.setObjectName("MutedLabel")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_button = QPushButton("下一页")
        self.next_button.setObjectName("SecondaryButton")
        self.next_button.clicked.connect(lambda: self._change_page(1))
        pagination.addWidget(self.previous_button)
        pagination.addWidget(self.page_label)
        pagination.addWidget(self.next_button)
        pagination.addStretch()
        layout.addLayout(pagination)

    def refresh(self) -> None:
        response = self.api.list_interviews(
            status=self._active_filter,
            page=self.current_page,
            page_size=self.page_size,
        )
        self.total_pages = response["total_pages"]
        self.total_records = response["total"]
        if self.current_page > self.total_pages:
            self.current_page = self.total_pages
            response = self.api.list_interviews(
                status=self._active_filter,
                page=self.current_page,
                page_size=self.page_size,
            )
            self.total_records = response["total"]
        self._render_cards(response["summary"])
        self._render_table(response["items"])
        self._update_pagination(response)

    def _render_table(self, records: list[dict]) -> None:
        self._loading = True
        self.table.clearContents()
        self.table.setRowCount(len(records))
        self._original_records = {record["id"]: _normalize_record(record) for record in records}
        self._dirty_ids.clear()

        for row, record in enumerate(records):
            interview_id = record["id"]
            marker = QTableWidgetItem("")
            marker.setData(Qt.ItemDataRole.UserRole, interview_id)
            marker.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, self.MARKER_COLUMN, marker)

            editable_values = {
                self.COMPANY_COLUMN: record["company_name"],
                self.POSITION_COLUMN: record["position_name"],
                self.BASE_COLUMN: record["base_location"],
            }
            for column, value in editable_values.items():
                text = str(value)
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, column, item)

            status_combo = QComboBox()
            status_combo.setObjectName("TableEditor")
            status_combo.addItems(self.STATUS_OPTIONS)
            _color_status_items(status_combo)
            if record["current_status"] not in self.STATUS_OPTIONS:
                status_combo.addItem(record["current_status"])
            status_combo.setCurrentText(record["current_status"])
            _apply_status_tone(status_combo, record["current_status"])
            status_combo.currentTextChanged.connect(
                lambda value, record_id=interview_id, editor=status_combo: self._on_status_changed(
                    record_id, editor, value
                )
            )
            self.table.setCellWidget(row, self.STATUS_COLUMN, status_combo)

            interview_time = OptionalDateTimeEdit(record["interview_time"])
            interview_time.setObjectName("TableEditor")
            _update_datetime_tooltip(interview_time, allow_empty=True)
            interview_time.dateTimeChanged.connect(
                lambda _value, record_id=interview_id, editor=interview_time: self._on_datetime_changed(
                    record_id, editor, allow_empty=True
                )
            )
            self.table.setCellWidget(row, self.INTERVIEW_TIME_COLUMN, interview_time)

            updated_at = QDateTimeEdit(_parse_datetime(record["updated_at"]))
            updated_at.setObjectName("TableEditor")
            updated_at.setCalendarPopup(True)
            updated_at.setDisplayFormat("yyyy-MM-dd HH:mm")
            _update_datetime_tooltip(updated_at)
            updated_at.dateTimeChanged.connect(
                lambda _value, record_id=interview_id, editor=updated_at: self._on_datetime_changed(
                    record_id, editor
                )
            )
            self.table.setCellWidget(row, self.UPDATED_AT_COLUMN, updated_at)

        self._loading = False
        self._update_save_state()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() == self.MARKER_COLUMN:
            return
        item.setToolTip(item.text())
        interview_id = self._record_id_for_row(item.row())
        if interview_id is not None:
            self._mark_record_changed(interview_id)

    def _on_status_changed(
        self, interview_id: int, editor: QComboBox, value: str
    ) -> None:
        _apply_status_tone(editor, value)
        self._mark_record_changed(interview_id)

    def _on_datetime_changed(
        self,
        interview_id: int,
        editor: QDateTimeEdit,
        allow_empty: bool = False,
    ) -> None:
        _update_datetime_tooltip(editor, allow_empty=allow_empty)
        self._mark_record_changed(interview_id)

    def _mark_record_changed(self, interview_id: int) -> None:
        if self._loading:
            return
        row = self._row_for_record(interview_id)
        if row is None:
            return
        current = self._record_from_row(row)
        if current == self._original_records.get(interview_id):
            self._dirty_ids.discard(interview_id)
        else:
            self._dirty_ids.add(interview_id)
        self._set_row_marker(row, interview_id in self._dirty_ids)
        self._update_save_state()

    def _record_from_row(self, row: int) -> dict:
        interview_id = self._record_id_for_row(row)
        status_editor = self.table.cellWidget(row, self.STATUS_COLUMN)
        interview_time_editor = self.table.cellWidget(row, self.INTERVIEW_TIME_COLUMN)
        updated_at_editor = self.table.cellWidget(row, self.UPDATED_AT_COLUMN)
        assert isinstance(status_editor, QComboBox)
        assert isinstance(interview_time_editor, OptionalDateTimeEdit)
        assert isinstance(updated_at_editor, QDateTimeEdit)
        return {
            "id": interview_id,
            "company_name": self._item_text(row, self.COMPANY_COLUMN),
            "position_name": self._item_text(row, self.POSITION_COLUMN),
            "base_location": self._item_text(row, self.BASE_COLUMN),
            "current_status": status_editor.currentText(),
            "interview_time": interview_time_editor.value(),
            "updated_at": updated_at_editor.dateTime().toString("yyyy-MM-dd HH:mm"),
        }

    def save_changes(self) -> bool:
        if not self._dirty_ids:
            return True
        pending_ids = list(self._dirty_ids)
        try:
            for interview_id in pending_ids:
                row = self._row_for_record(interview_id)
                if row is None:
                    continue
                record = self._record_from_row(row)
                self.api.update_interview(
                    interview_id=interview_id,
                    company_name=record["company_name"],
                    position_name=record["position_name"],
                    base_location=record["base_location"],
                    current_status=record["current_status"],
                    interview_time=record["interview_time"],
                    updated_at=record["updated_at"],
                )
        except Exception as exc:  # HTTP 客户端负责将底层错误转换为用户可读的接口错误。
            QMessageBox.critical(self, "保存失败", f"修改未能保存：{exc}")
            return False

        count = len(pending_ids)
        self.refresh()
        self.save_feedback.setText(f"已保存 {count} 行")
        self.save_feedback.show()
        QTimer.singleShot(3000, self.save_feedback.hide)
        return True

    def discard_changes(self) -> None:
        self.refresh()

    def resolve_pending_changes(self, action: str) -> bool:
        """判断用户请求的页面切换或关闭操作是否可以继续。"""

        if not self.has_pending_changes:
            return True

        dialog = QMessageBox(self)
        dialog.setWindowTitle("有尚未保存的修改")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(f"当前有 {len(self._dirty_ids)} 行记录被修改。{action}前是否保留这些修改？")
        dialog.setInformativeText("保留修改会保存到当前数据源；放弃修改会恢复原来的内容。")
        keep_button = dialog.addButton("保留修改", QMessageBox.ButtonRole.AcceptRole)
        discard_button = dialog.addButton("放弃修改", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(keep_button)
        dialog.exec()

        clicked: QAbstractButton | None = dialog.clickedButton()
        if clicked is keep_button:
            return self.save_changes()
        if clicked is discard_button:
            self.discard_changes()
            return True
        if clicked is cancel_button:
            return False
        return False

    def _on_filter_changed(self, selected_filter: str) -> None:
        if selected_filter == self._active_filter:
            return
        if not self.resolve_pending_changes("切换筛选条件"):
            self.filter_combo.blockSignals(True)
            self.filter_combo.setCurrentText(self._active_filter)
            self.filter_combo.blockSignals(False)
            return
        self._active_filter = selected_filter
        self.current_page = 1
        _apply_status_tone(self.filter_combo, selected_filter)
        self.refresh()

    def _select_card_filter(self, selected_filter: str) -> None:
        if selected_filter == self._active_filter:
            return
        self.filter_combo.setCurrentText(selected_filter)

    def _change_page(self, offset: int) -> None:
        target_page = self.current_page + offset
        if target_page < 1 or target_page > self.total_pages:
            return
        if not self.resolve_pending_changes("切换分页"):
            return
        self.current_page = target_page
        self.refresh()

    def _update_pagination(self, response: dict) -> None:
        self.page_label.setText(
            f"第 {response['page']} / {response['total_pages']} 页 · 共 {response['total']} 条"
        )
        self.previous_button.setEnabled(response["has_previous"])
        self.next_button.setEnabled(response["has_next"])

    def _set_row_marker(self, row: int, dirty: bool) -> None:
        marker = self.table.item(row, self.MARKER_COLUMN)
        if marker is None:
            return
        self._loading = True
        marker.setText("*" if dirty else "")
        marker.setForeground(QColor("#8652E8"))
        font = marker.font()
        font.setBold(dirty)
        font.setPointSize(15)
        marker.setFont(font)
        self._loading = False

    def _update_save_state(self) -> None:
        count = len(self._dirty_ids)
        self.save_button.setEnabled(count > 0)
        self.save_button.setText(f"保存修改（{count}）" if count else "保存修改")

    def _record_id_for_row(self, row: int) -> int | None:
        marker = self.table.item(row, self.MARKER_COLUMN)
        return marker.data(Qt.ItemDataRole.UserRole) if marker else None

    def _row_for_record(self, interview_id: int) -> int | None:
        for row in range(self.table.rowCount()):
            if self._record_id_for_row(row) == interview_id:
                return row
        return None

    def _item_text(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text().strip() if item else ""

    def _render_cards(self, summary: dict) -> None:
        while self.cards.count():
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        status_counts = summary["status_counts"]
        for label, filter_value in self.SUMMARY_CARDS:
            count = summary["total"] if filter_value == "全部" else status_counts[filter_value]
            card = SummaryCard(filter_value)
            card.setProperty("active", filter_value == self._active_filter)
            card.setProperty("statusTone", _status_tone(filter_value))
            card.clicked.connect(self._select_card_filter)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 13, 15, 13)
            card_layout.setSpacing(4)
            name = QLabel(label)
            name.setObjectName("CardLabel")
            name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            value = QLabel(f"{count:02d}")
            value.setObjectName("CardValue")
            value.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            card_layout.addWidget(name)
            card_layout.addWidget(value)
            self.cards.addWidget(card)

    def _sync_email(self) -> None:
        if self.runner.busy or self._email_task_id:
            return
        self._integration_busy("正在提交邮件扫描…")
        self.runner.start("sync_email", self._email_started)

    def _email_started(self, result):
        self._email_task_id = result["task_id"]
        self.integration_notice.setText("正在扫描邮件…")
        if hasattr(self.api, "get_task"):
            self._poll_timer.start()
        else:
            self._email_task_id = None

    def _poll_email(self):
        if self._email_task_id and not self.runner.busy:
            self.runner.start("get_task", self._email_progress, task_id=self._email_task_id)

    def _email_progress(self, result):
        if result["status"] in {"accepted", "running"}:
            return
        self._poll_timer.stop()
        self._email_task_id = None
        data = result["result"]
        self.integration_notice.setText(result.get("error") or
            f"邮件扫描完成：更新 {data.get('updated', 0)} 条，需核对 {len(data.get('needs_review', []))} 封，失败 {data.get('failed', 0)} 封。")
        if not self.has_pending_changes:
            self.refresh()

    def _sync_feishu(self) -> None:
        if self.runner.busy:
            return
        self._integration_busy("正在同步飞书…")
        self.runner.start("sync_feishu", self._feishu_finished)

    def _feishu_finished(self, result):
        review = len(result.get("needs_review", []))
        self.integration_notice.setText(f"飞书同步完成：成功 {result['success_count']} 条，失败 {result['failed_count']} 条，需核对 {review} 条。")
        if not self.has_pending_changes:
            self.refresh()

    def _integration_busy(self, message):
        self.integration_notice.setText(message)
        self.email_button.setEnabled(False)
        self.feishu_button.setEnabled(False)

    def _integration_ready(self):
        self.email_button.setEnabled(self._email_task_id is None)
        self.feishu_button.setEnabled(True)

    def _integration_error(self, message):
        self._poll_timer.stop()
        self._email_task_id = None
        self.integration_notice.setText(message)


def _parse_datetime(value: str | None) -> QDateTime:
    """解析旧版界面时间格式或服务端 ISO 8601 时间戳。
    
    参数:
        value: Mock 或 HTTP 客户端返回的可空时间戳。
    
    返回值:
        解析后的 Qt 日期时间对象；解析失败时返回无效对象。
    """
    if not value:
        return QDateTime()
    for date_format in ("yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm"):
        parsed = QDateTime.fromString(value, date_format)
        if parsed.isValid():
            return parsed
    parsed = QDateTime.fromString(value, Qt.DateFormat.ISODate)
    if parsed.isValid():
        return parsed
    return QDateTime()


def _normalize_record(record: dict) -> dict:
    normalized = deepcopy(record)
    normalized["interview_time"] = _normalized_datetime_text(record.get("interview_time"))
    normalized["updated_at"] = _normalized_datetime_text(record.get("updated_at")) or ""
    return {
        key: normalized.get(key)
        for key in (
            "id",
            "company_name",
            "position_name",
            "base_location",
            "current_status",
            "interview_time",
            "updated_at",
        )
    }


def _normalized_datetime_text(value: str | None) -> str | None:
    parsed = _parse_datetime(value)
    return parsed.toString("yyyy-MM-dd HH:mm") if parsed.isValid() else None


def _status_tone(status: str) -> str:
    if status == "已投递":
        return "applied"
    if status == "待面试":
        return "pending"
    if status == "Offer":
        return "offer"
    if status == "已结束":
        return "ended"
    return "default"


def _apply_status_tone(widget: QWidget, status: str) -> None:
    widget.setProperty("statusTone", _status_tone(status))
    widget.setToolTip(status)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _color_status_items(combo: QComboBox) -> None:
    for index in range(combo.count()):
        status = combo.itemText(index)
        if status == "已投递":
            combo.setItemData(index, QColor("#41699B"), Qt.ItemDataRole.ForegroundRole)
            combo.setItemData(index, QColor("#EAF2FB"), Qt.ItemDataRole.BackgroundRole)
        elif status == "Offer":
            combo.setItemData(index, QColor("#238B63"), Qt.ItemDataRole.ForegroundRole)
            combo.setItemData(index, QColor("#E6F8EF"), Qt.ItemDataRole.BackgroundRole)
        elif status == "待面试":
            combo.setItemData(index, QColor("#9A6500"), Qt.ItemDataRole.ForegroundRole)
            combo.setItemData(index, QColor("#FFF5D9"), Qt.ItemDataRole.BackgroundRole)
        elif status == "已结束":
            combo.setItemData(index, QColor("#777382"), Qt.ItemDataRole.ForegroundRole)
            combo.setItemData(index, QColor("#F0EEF3"), Qt.ItemDataRole.BackgroundRole)


def _update_datetime_tooltip(
    editor: QDateTimeEdit, allow_empty: bool = False
) -> None:
    if allow_empty and isinstance(editor, OptionalDateTimeEdit) and editor.value() is None:
        editor.setToolTip("无面试时间；点击选择，按 Delete 或 Backspace 清空")
        return
    editor.setToolTip(editor.dateTime().toString("yyyy-MM-dd HH:mm"))
