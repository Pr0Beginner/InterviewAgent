from __future__ import annotations

from html import escape

from PySide6.QtCore import QEvent, QPoint, QTimer, Signal, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from client.api.base import ApiClient
from client.ui.icons import app_icon
from client.ui.widgets.api_task import TaskRunner
from client.ui.widgets.glass_combo import GlassComboBox
from client.ui.widgets.status_notice import StatusNotice


CITY_OPTIONS = (
    "北京", "上海", "广州", "深圳", "杭州", "南京", "苏州",
    "武汉", "成都", "西安", "长沙", "天津", "重庆",
)
WORK_EXPERIENCE_OPTIONS = (
    "不限", "应届生", "1年以内", "1-3年", "3-5年", "5-10年", "10年以上",
)


def _split_values(value: str) -> list[str]:
    return list(dict.fromkeys(
        item.strip() for item in value.replace("，", ",").split(",") if item.strip()
    ))


class CityMultiSelect(QWidget):
    """保持菜单展开的多选城市控件，向业务层只暴露已选择城市列表。"""

    selection_changed = Signal(list)

    def __init__(self, selected: list[str] | None = None, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton()
        self.button.setObjectName("CityPicker")
        self.button.setAccessibleName("目标城市，多选")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu = QMenu(self.button)
        self.menu.setObjectName("CityPickerMenu")
        self.options: dict[str, QCheckBox] = {}
        chosen = set(selected or [])
        for city in CITY_OPTIONS:
            checkbox = QCheckBox(city)
            checkbox.setObjectName("CityOption")
            checkbox.setMinimumWidth(176)
            checkbox.setChecked(city in chosen)
            checkbox.toggled.connect(self._selection_updated)
            action = QWidgetAction(self.menu)
            action.setDefaultWidget(checkbox)
            self.menu.addAction(action)
            self.options[city] = checkbox
        self.button.setMenu(self.menu)
        layout.addWidget(self.button)
        self._selection_updated()

    def selected_cities(self) -> list[str]:
        return [city for city, option in self.options.items() if option.isChecked()]

    def set_selected_cities(self, cities: list[str]) -> None:
        selected = set(cities)
        for city, option in self.options.items():
            option.blockSignals(True)
            option.setChecked(city in selected)
            option.blockSignals(False)
        self._selection_updated()

    def _selection_updated(self) -> None:
        selected = self.selected_cities()
        if not selected:
            caption = "不限城市"
        elif len(selected) <= 3:
            caption = "、".join(selected)
        else:
            caption = "、".join(selected[:3]) + f" 等 {len(selected)} 个城市"
        self.button.setText(caption)
        self.button.setToolTip("已选择：" + ("、".join(selected) if selected else "不限城市"))
        self.selection_changed.emit(selected)


class JobDescriptionBubble(QFrame):
    """脱离岗位卡片布局的 JD 气泡，进入气泡时保持显示。"""

    def __init__(self, description: str, owner) -> None:
        super().__init__(owner, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.owner = owner
        self.setObjectName("JdPreview")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(390, 250)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(9)

        title = QLabel("岗位 JD")
        title.setObjectName("JdBubbleTitle")
        layout.addWidget(title)

        detail = QTextBrowser()
        detail.setObjectName("JdText")
        detail.setPlainText(description or "该岗位暂未提供 JD。")
        detail.setOpenExternalLinks(False)
        detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(detail, 1)

    def enterEvent(self, event) -> None:
        self.owner._bubble_hovered = True
        self.owner._cancel_hide()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.owner._bubble_hovered = False
        self.owner._schedule_hide()
        super().leaveEvent(event)


class HoverJobDescription(QFrame):
    """卡片内只保留触发文字，悬浮或聚焦时显示独立的 JD 气泡。"""

    def __init__(self, description: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("JdHoverArea")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.trigger = QLabel("查看岗位 JD")
        self.trigger.setObjectName("JdTrigger")
        self.trigger.setCursor(Qt.CursorShape.PointingHandCursor)
        self.trigger.setAccessibleName("查看岗位 JD，鼠标悬浮或键盘聚焦后显示")
        self.trigger.installEventFilter(self)
        layout.addWidget(self.trigger)

        self.preview = JobDescriptionBubble(description, self)
        self._owner_hovered = False
        self._bubble_hovered = False
        self._keyboard_focus = False
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(140)
        self._hide_timer.timeout.connect(self._hide_if_inactive)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.trigger:
            if event.type() == QEvent.Type.Enter:
                self._owner_hovered = True
                self._show_preview()
            elif event.type() == QEvent.Type.Leave:
                self._owner_hovered = False
                self._schedule_hide()
        return super().eventFilter(watched, event)

    def _show_preview(self) -> None:
        self._cancel_hide()
        anchor = self.trigger.mapToGlobal(QPoint(self.trigger.width(), self.trigger.height()))
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        x = anchor.x() - self.preview.width()
        y = anchor.y() + 8
        x = max(available.left() + 8, min(x, available.right() - self.preview.width() - 8))
        if y + self.preview.height() > available.bottom() - 8:
            top = self.trigger.mapToGlobal(QPoint(0, 0)).y()
            y = max(available.top() + 8, top - self.preview.height() - 8)
        self.preview.move(x, y)
        self.preview.show()
        self.preview.raise_()

    def _schedule_hide(self) -> None:
        self._hide_timer.start()

    def _cancel_hide(self) -> None:
        self._hide_timer.stop()

    def _hide_if_inactive(self) -> None:
        if not self._keyboard_focus and not self._owner_hovered and not self._bubble_hovered:
            self.preview.hide()

    def enterEvent(self, event) -> None:
        self._owner_hovered = True
        self._show_preview()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._owner_hovered = False
        self._schedule_hide()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        self._keyboard_focus = True
        self._show_preview()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self._keyboard_focus = False
        self._schedule_hide()
        super().focusOutEvent(event)


class JobsPage(QWidget):
    event_message = Signal(str)

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.current_page = 1
        self.page_size = 5
        self.total_pages = 1
        self._search_filters = None
        self.current_search_id = None
        self.current_result_count = 0
        self.runner = TaskRunner(api, self)
        self.runner.failed.connect(self._show_error)
        self.runner.idle.connect(self._ready)
        self._build_ui()
        self._load_jobs(cached_only=True)

    def _build_ui(self) -> None:
        self.setObjectName("PageSurface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(14)

        title = QLabel("推荐岗位")
        title.setObjectName("PageTitle")
        subtitle = QLabel("先按城市找到真实岗位，再由 Agent 阅读 JD 并排序")
        subtitle.setObjectName("PageSubtitle")
        heading = QVBoxLayout()
        heading.setSpacing(5)
        heading.addWidget(title)
        heading.addWidget(subtitle)
        layout.addLayout(heading)

        filter_frame = QFrame()
        filter_frame.setObjectName("JobSearchToolbar")
        filters = QHBoxLayout(filter_frame)
        filters.setContentsMargins(16, 13, 16, 13)
        filters.setSpacing(14)

        self.city_picker = CityMultiSelect(["上海", "杭州"])
        self.experience_combo = GlassComboBox()
        self.experience_combo.addItems(WORK_EXPERIENCE_OPTIONS)
        self.experience_combo.setCurrentText("应届生")
        self.experience_combo.setAccessibleName("工作经验")
        self.keyword_input = QLineEdit("Java 后端")
        self.keyword_input.setPlaceholderText("例如：Java 后端、分布式开发")
        self.keyword_input.setAccessibleName("岗位关键词")
        for caption, field, stretch in (
            ("目标城市（可多选）", self.city_picker, 2),
            ("工作经验", self.experience_combo, 1),
            ("岗位关键词", self.keyword_input, 3),
        ):
            group = QVBoxLayout()
            group.setSpacing(6)
            label = QLabel(caption)
            label.setObjectName("JobFilterLabel")
            label.setBuddy(field)
            group.addWidget(label)
            group.addWidget(field)
            filters.addLayout(group, stretch)

        self.search_button = QPushButton("搜索并分析")
        self.search_button.setObjectName("PrimaryButton")
        self.search_button.setIcon(app_icon("search", "#FFFFFF"))
        self.search_button.clicked.connect(self.search_jobs)
        filters.addWidget(self.search_button)
        filters.setAlignment(self.search_button, Qt.AlignmentFlag.AlignBottom)
        layout.addWidget(filter_frame)

        self.notice = StatusNotice()
        self.notice.setWordWrap(True)
        self.notice.setObjectName("JobNotice")
        layout.addWidget(self.notice)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 8, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch()
        scroll.setWidget(self.list_container)
        layout.addWidget(scroll, 1)

        pagination = QHBoxLayout()
        pagination.addStretch()
        self.previous_button = QPushButton("上一页")
        self.previous_button.setObjectName("SecondaryButton")
        self.previous_button.clicked.connect(lambda: self._change_page(-1))
        self.page_label = QLabel("第 1 / 1 页")
        self.page_label.setObjectName("MutedLabel")
        self.next_button = QPushButton("下一页")
        self.next_button.setObjectName("SecondaryButton")
        self.next_button.clicked.connect(lambda: self._change_page(1))
        pagination.addWidget(self.previous_button)
        pagination.addWidget(self.page_label)
        pagination.addWidget(self.next_button)
        pagination.addStretch()
        layout.addLayout(pagination)

    def search_jobs(self) -> None:
        if self.runner.busy:
            return
        self.current_page = 1
        self._load_jobs(refresh=True)

    def agent_context(self) -> dict:
        """返回问答发送瞬间的筛选状态；仅在内存中传给当前 Agent 请求。"""
        filters = {
            "cities": self.city_picker.selected_cities(),
            "work_experience": self.experience_combo.currentText(),
            "keywords": _split_values(self.keyword_input.text()),
        }
        same_as_loaded = filters == self._search_filters
        return {
            **filters,
            "search_id": self.current_search_id if same_as_loaded else None,
            "result_count": self.current_result_count if same_as_loaded else 0,
        }

    def _load_jobs(self, refresh: bool = False, cached_only: bool = False) -> None:
        if refresh or self._search_filters is None:
            self._search_filters = {
                "cities": self.city_picker.selected_cities(),
                "work_experience": self.experience_combo.currentText(),
                "keywords": _split_values(self.keyword_input.text()),
            }
        self.search_button.setEnabled(False)
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.notice.setText("正在加载…" if cached_only else "正在抓取岗位并由 Agent 阅读 JD，请稍候…")
        self.runner.start(
            "recommend_jobs",
            self._loaded,
            **self._search_filters,
            page=self.current_page,
            page_size=self.page_size,
            extensions={"refresh": refresh, "cached_only": cached_only},
        )

    def _loaded(self, result):
        """渲染服务端结果，失败时不使用演示数据替代。"""
        self.total_pages = result["total_pages"]
        self.current_search_id = result.get("search_id")
        self.current_result_count = result["total"]
        self._render_jobs(result["items"])
        self.page_label.setText(
            f"第 {result['page']} / {result['total_pages']} 页 · 共 {result['total']} 个岗位"
        )
        self.previous_button.setEnabled(result["has_previous"])
        self.next_button.setEnabled(result["has_next"])
        self.notice.setText(result.get("message") or f"已整理 {result['total']} 个真实岗位，按 Agent 判断结果排序。")

    def _show_error(self, message):
        self.notice.setText(message)

    def _ready(self):
        self.search_button.setEnabled(True)

    def _change_page(self, offset: int) -> None:
        if self.runner.busy:
            return
        target_page = self.current_page + offset
        if target_page < 1 or target_page > self.total_pages:
            return
        self.current_page = target_page
        self._load_jobs()

    def _render_jobs(self, jobs: list[dict]) -> None:
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not jobs:
            empty = QLabel("还没有岗位结果。选择城市和关键词后开始搜索。")
            empty.setObjectName("JobEmptyState")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_layout.insertWidget(0, empty)
            return
        start = (self.current_page - 1) * self.page_size + 1
        for offset, job in enumerate(jobs):
            self.list_layout.insertWidget(
                self.list_layout.count() - 1,
                self._create_card(job, start + offset),
            )

    def _create_card(self, job: dict, sequence: int) -> QFrame:
        card = QFrame()
        card.setObjectName("JobResultRow")
        row = QHBoxLayout(card)
        row.setContentsMargins(18, 16, 18, 16)
        row.setSpacing(16)

        number = QLabel(f"{sequence:02d}")
        number.setObjectName("JobSequence")
        number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        number.setFixedSize(46, 46)
        row.addWidget(number, 0, Qt.AlignmentFlag.AlignTop)

        content = QVBoxLayout()
        content.setSpacing(11)
        fields = QGridLayout()
        fields.setHorizontalSpacing(22)
        fields.setVerticalSpacing(4)
        fields.addWidget(self._field_label("公司"), 0, 0)
        fields.addWidget(self._field_label("岗位"), 0, 1)
        fields.addWidget(self._field_value(job.get("company_name") or "待确认", prominent=True), 1, 0)
        fields.addWidget(self._field_value(job.get("position_name") or "待确认", prominent=True), 1, 1)
        fields.addWidget(self._field_label("地点"), 2, 0)
        fields.addWidget(self._field_label("薪资范围"), 2, 1)
        fields.addWidget(self._field_value(job.get("base_location") or "待确认"), 3, 0)
        fields.addWidget(self._field_value(job.get("salary") or "待确认", salary=True), 3, 1)
        fields.setColumnStretch(0, 2)
        fields.setColumnStretch(1, 3)
        content.addLayout(fields)

        actions = QFrame(card)
        actions.setObjectName("JobActions")
        actions.setMinimumWidth(180)
        actions.setMaximumWidth(300)
        action_layout = QVBoxLayout(actions)
        action_layout.setContentsMargins(16, 2, 0, 2)
        action_layout.setSpacing(8)

        url = str(job.get("job_url") or "")
        if url:
            link = QLabel(f'<a href="{escape(url, quote=True)}">打开岗位链接</a>', actions)
            link.setOpenExternalLinks(True)
            link.setToolTip(url)
        else:
            link = QLabel("岗位链接待确认", actions)
        link.setObjectName("JobLink")
        link.setAccessibleName("岗位链接")
        link.setAlignment(Qt.AlignmentFlag.AlignRight)
        action_layout.addWidget(link)

        jd = HoverJobDescription(job.get("job_description") or "", actions)
        jd.trigger.setAlignment(Qt.AlignmentFlag.AlignRight)
        action_layout.addWidget(jd, 0, Qt.AlignmentFlag.AlignRight)
        action_layout.addStretch()
        row.addLayout(content, 1)
        row.addWidget(actions, 0, Qt.AlignmentFlag.AlignTop)
        return card

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("JobFieldLabel")
        return label

    @staticmethod
    def _field_value(text: str, prominent: bool = False, salary: bool = False) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setObjectName("JobSalary" if salary else "JobPrimaryValue" if prominent else "JobFieldValue")
        return label
