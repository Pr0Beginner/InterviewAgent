from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QDateTime, QEvent, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from client.api.base import ApiClient
from client.ui.icons import app_icon
from client.ui.widgets.api_task import TaskRunner
from client.ui.widgets.datetime_picker import DateTimePicker
from client.ui.widgets.dialogs import AppDialog
from client.ui.widgets.status_notice import StatusNotice
from client.ui.widgets.glass import soft_shadow
from client.ui.widgets.glass_combo import GlassComboBox


class SummaryCard(QFrame):
    clicked = Signal(str)

    def __init__(self, filter_value: str, parent=None) -> None:
        super().__init__(parent)
        self.filter_value = filter_value
        self.setObjectName("SummaryCard")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"筛选{filter_value}投递")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit(self.filter_value)
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.filter_value)
        super().mouseReleaseEvent(event)


class DashboardPage(QWidget):
    event_message = Signal(str)
    email_candidates = Signal(list)

    STATUS_OPTIONS = ["已投递", "简历筛选中", "笔试中", "待面试", "一面", "二面", "三面", "HR面", "Offer", "已结束"]
    SUMMARY_CARDS = [
        ("全部投递", "全部"),
        ("笔试中", "笔试中"),
        ("待面试", "待面试"),
        ("Offer", "Offer"),
    ]

    MARKER_COLUMN = 0
    COMPANY_COLUMN = 1
    POSITION_COLUMN = 2
    BASE_COLUMN = 3
    STATUS_COLUMN = 4
    START_TIME_COLUMN = 5
    END_TIME_COLUMN = 6
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
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(16)

        header = QHBoxLayout()
        heading_box = QVBoxLayout()
        heading_box.setSpacing(6)
        title = QLabel("投递进度")
        title.setObjectName("PageTitle")
        subtitle = QLabel("每一份投递，每一步进展")
        subtitle.setObjectName("PageSubtitle")
        heading_box.addWidget(title)
        heading_box.addWidget(subtitle)

        email_button = self.email_button = QPushButton("扫描未读邮件")
        email_button.setObjectName("SecondaryButton")
        email_button.setIcon(app_icon("mail"))
        email_button.clicked.connect(self._sync_email)
        header.addLayout(heading_box)
        header.addStretch()
        header.addWidget(email_button)
        layout.addLayout(header)
        self.integration_notice = StatusNotice()
        self.integration_notice.setWordWrap(True)
        self.integration_notice.setObjectName("MutedLabel")
        layout.addWidget(self.integration_notice)
        layout.setSpacing(16)

        summary_group = QFrame()
        summary_group.setObjectName("SummaryGroup")
        self.cards = QHBoxLayout(summary_group)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(14)
        layout.addWidget(summary_group)

        table_surface = QFrame()
        table_surface.setObjectName("TableSurface")
        soft_shadow(table_surface, blur=22, opacity=10, offset=6)
        table_layout = QVBoxLayout(table_surface)
        table_layout.setContentsMargins(1, 1, 1, 1)
        table_layout.setSpacing(0)

        toolbar = QFrame()
        toolbar.setObjectName("TableToolbar")
        controls = QHBoxLayout(toolbar)
        controls.setContentsMargins(14, 12, 14, 12)
        table_title = QLabel("投递记录")
        table_title.setObjectName("SectionTitle")
        controls.addWidget(table_title)
        controls.addSpacing(14)
        self.filter_combo = GlassComboBox()
        self.filter_combo.setObjectName("StatusFilter")
        self.filter_combo.addItems(["全部", *self.STATUS_OPTIONS])
        _configure_status_combo(self.filter_combo)
        _apply_status_tone(self.filter_combo, "全部")
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        self.save_button = QPushButton("保存修改")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_changes)
        self.discard_button = QPushButton("放弃修改")
        self.discard_button.setObjectName("DangerButton")
        self.discard_button.setEnabled(False)
        self.discard_button.clicked.connect(self._confirm_discard_changes)
        controls.addWidget(QLabel("状态"))
        controls.addWidget(self.filter_combo)
        controls.addStretch()
        self.save_feedback = QLabel("")
        self.save_feedback.setObjectName("SaveFeedback")
        self.save_feedback.hide()
        controls.addWidget(self.save_feedback)
        controls.addWidget(self.discard_button)
        controls.addWidget(self.save_button)
        table_layout.addWidget(toolbar)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["", "公司", "岗位", "城市", "当前状态", "开始时间", "结束时间"]
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
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.itemChanged.connect(self._on_item_changed)
        header_view = self.table.horizontalHeader()
        header_view.setSectionsMovable(False)
        header_view.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header_view.setMinimumSectionSize(20)
        header_view.setStretchLastSection(False)
        for column, width in {
            self.MARKER_COLUMN: 20,
            self.COMPANY_COLUMN: 140,
            self.POSITION_COLUMN: 280,
            self.BASE_COLUMN: 80,
            self.STATUS_COLUMN: 150,
            self.START_TIME_COLUMN: 180,
            self.END_TIME_COLUMN: 180,
        }.items():
            header_view.resizeSection(column, width)
        self.table.viewport().installEventFilter(self)
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.table)
        empty = QLabel("暂无投递记录\n\n可以通过 Agent 添加投递记录。")
        empty.setObjectName("MutedLabel")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        self.table_stack.addWidget(empty)
        table_layout.addWidget(self.table_stack, 1)

        pagination = QHBoxLayout()
        pagination.setSpacing(10)
        pagination.setContentsMargins(14, 12, 14, 12)
        self.record_count = QLabel()
        self.record_count.setObjectName("MutedLabel")
        pagination.addWidget(self.record_count)
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
        table_layout.addLayout(pagination)
        layout.addWidget(table_surface, 1)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.table.viewport() and event.type() == QEvent.Type.Resize:
            # Give spare width to job titles; keep both date columns identical.
            fixed_width = sum(
                self.table.columnWidth(column)
                for column in range(self.table.columnCount())
                if column != self.POSITION_COLUMN
            )
            self.table.setColumnWidth(
                self.POSITION_COLUMN, max(280, self.table.viewport().width() - fixed_width)
            )
        return super().eventFilter(watched, event)

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
        self.table_stack.setCurrentIndex(0 if records else 1)
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
                if column == self.COMPANY_COLUMN:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setForeground(QColor("#1D1D1F"))
                self.table.setItem(row, column, item)

            status_combo = GlassComboBox()
            status_combo.setObjectName("TableEditor")
            status_combo.addItems(self.STATUS_OPTIONS)
            _configure_status_combo(status_combo)
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

            start_time = DateTimePicker(record.get("interview_time"), "选择开始时间")
            start_time.dateTimeChanged.connect(
                lambda record_id=interview_id: self._on_datetime_changed(record_id)
            )
            self.table.setCellWidget(row, self.START_TIME_COLUMN, start_time)

            end_time = DateTimePicker(record.get("interview_end_time"), "选择结束时间")
            end_time.dateTimeChanged.connect(
                lambda record_id=interview_id: self._on_datetime_changed(record_id)
            )
            self.table.setCellWidget(row, self.END_TIME_COLUMN, end_time)

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
    ) -> None:
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
        start_time_editor = self.table.cellWidget(row, self.START_TIME_COLUMN)
        end_time_editor = self.table.cellWidget(row, self.END_TIME_COLUMN)
        assert isinstance(status_editor, QComboBox)
        assert isinstance(start_time_editor, DateTimePicker)
        assert isinstance(end_time_editor, DateTimePicker)
        return {
            "id": interview_id,
            "company_name": self._item_text(row, self.COMPANY_COLUMN),
            "position_name": self._item_text(row, self.POSITION_COLUMN),
            "base_location": self._item_text(row, self.BASE_COLUMN),
            "current_status": status_editor.currentText(),
            "interview_time": start_time_editor.value(),
            "interview_end_time": end_time_editor.value(),
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
                    interview_end_time=record["interview_end_time"],
                )
        except Exception as exc:  # HTTP 客户端负责将底层错误转换为用户可读的接口错误。
            AppDialog.show_error(self, "保存失败", f"修改未能保存：{exc}")
            return False

        count = len(pending_ids)
        self.refresh()
        self.save_feedback.setText(f"已保存 {count} 行")
        self.save_feedback.show()
        QTimer.singleShot(3000, self.save_feedback.hide)
        return True

    def discard_changes(self) -> None:
        self.refresh()

    def _confirm_discard_changes(self) -> None:
        """通过统一样式的弹窗确认主动放弃本页修改。"""
        if not self.has_pending_changes:
            return
        result = AppDialog(
            self,
            title="放弃本页修改",
            message=f"将撤销当前 {len(self._dirty_ids)} 行尚未保存的修改。",
            detail="该操作只恢复表格内容，不会影响已经保存到服务端的数据。",
            primary_text="继续编辑",
            destructive_text="放弃修改",
            cancel_text=None,
        ).exec()
        if result == AppDialog.DESTRUCTIVE:
            self.discard_changes()

    def resolve_pending_changes(self, action: str) -> bool:
        """判断用户请求的页面切换或关闭操作是否可以继续。"""

        if not self.has_pending_changes:
            return True

        result = AppDialog(
            self,
            title="有尚未保存的修改",
            message=f"当前有 {len(self._dirty_ids)} 行记录被修改。{action}前是否保存？",
            detail="保存后继续当前操作；放弃修改会恢复为服务端中的内容。",
            primary_text="保留修改",
            destructive_text="放弃修改",
            cancel_text="取消",
        ).exec()
        if result == AppDialog.PRIMARY:
            return self.save_changes()
        if result == AppDialog.DESTRUCTIVE:
            self.discard_changes()
            return True
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
            f"{response['page']} / {response['total_pages']}"
        )
        self.record_count.setText(f"共 {response['total']} 条投递")
        self.previous_button.setEnabled(response["has_previous"])
        self.next_button.setEnabled(response["has_next"])

    def _set_row_marker(self, row: int, dirty: bool) -> None:
        marker = self.table.item(row, self.MARKER_COLUMN)
        if marker is None:
            return
        self._loading = True
        marker.setText("*" if dirty else "")
        marker.setForeground(QColor("#9273D5"))
        font = marker.font()
        font.setBold(dirty)
        font.setPointSize(15)
        marker.setFont(font)
        self._loading = False

    def _update_save_state(self) -> None:
        count = len(self._dirty_ids)
        self.save_button.setEnabled(count > 0)
        self.discard_button.setEnabled(count > 0)
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
        for (label, filter_value), icon_name in zip(self.SUMMARY_CARDS, ("case", "grid", "calendar", "check")):
            count = summary["total"] if filter_value == "全部" else status_counts[filter_value]
            card = SummaryCard(filter_value)
            soft_shadow(card, blur=18, opacity=16, offset=6)
            card.setProperty("active", filter_value == self._active_filter)
            card.setProperty("statusTone", _status_tone(filter_value))
            card.clicked.connect(self._select_card_filter)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 14, 18, 14)
            card_layout.setSpacing(10)
            name = QLabel(label)
            name.setObjectName("CardLabel")
            name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            card_header = QHBoxLayout()
            card_header.addWidget(name)
            card_header.addStretch()
            glyph = QLabel()
            glyph.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            glyph.setPixmap(app_icon(icon_name, "#739680" if filter_value == "Offer" else "#9A88B5").pixmap(QSize(20, 20)))
            card_header.addWidget(glyph)
            value = QLabel(str(count))
            value.setObjectName("CardValue")
            value.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            card_layout.addLayout(card_header)
            card_layout.addWidget(value)
            self.cards.addWidget(card, 1)

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
        candidates = data.get("creation_candidates", [])
        self.integration_notice.setText(result.get("error") or
            f"邮件扫描完成：更新 {data.get('updated', 0)} 条，待创建 {len(candidates)} 条，需核对 {len(data.get('needs_review', []))} 封，失败 {data.get('failed', 0)} 封。")
        if candidates:
            self.email_candidates.emit(candidates)
        if not self.has_pending_changes:
            self.refresh()

    def _integration_busy(self, message):
        self.integration_notice.setText(message)
        self.email_button.setEnabled(False)

    def _integration_ready(self):
        self.email_button.setEnabled(self._email_task_id is None)

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
    normalized["interview_end_time"] = _normalized_datetime_text(record.get("interview_end_time"))
    return {
        key: normalized.get(key)
        for key in (
            "id",
            "company_name",
            "position_name",
            "base_location",
            "current_status",
            "interview_time",
            "interview_end_time",
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


def _configure_status_combo(combo: QComboBox) -> None:
    """限制状态弹层高度；弹层内仍可通过滚轮或滚动条浏览全部状态。"""
    combo.setMaxVisibleItems(6)
    combo.setProperty("statusSelector", True)
    combo.view().setMaximumHeight(256)
    combo.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    combo.view().setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
