from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QCloseEvent, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from client.api.base import ApiClient
from client.styles import APP_STYLE
from client.ui.pages import DashboardPage, JobsPage, MockInterviewPage
from client.ui.widgets import AgentPanel


class MainWindow(QMainWindow):
    PAGE_CONTEXT_BY_INDEX = {
        0: "applications",
        1: "recommendations",
        2: "mock_interview",
    }

    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api
        self._closing_after_agent = False
        self.setWindowTitle("Interview Assistant")
        self.resize(1680, 960)
        self.setMinimumSize(1360, 780)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("AppRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(205)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 24, 18, 20)
        sidebar_layout.setSpacing(10)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(4, 0, 0, 16)
        brand_row.setSpacing(10)
        brand_mark = QLabel("A")
        brand_mark.setObjectName("BrandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand = QLabel("秋招 Agent")
        brand.setObjectName("BrandText")
        brand_row.addWidget(brand_mark)
        brand_row.addWidget(brand)
        brand_row.addStretch()
        sidebar_layout.addLayout(brand_row)

        self.pages = QStackedWidget()
        self.pages.setObjectName("PageStack")
        self.pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.agent_panel = AgentPanel(self.api)

        self.dashboard = DashboardPage(self.api)
        jobs = self.jobs_page = JobsPage(self.api)
        mock_interview = self.mock_page = MockInterviewPage(self.api)
        self.dashboard.event_message.connect(self.agent_panel.add_system_message)
        jobs.event_message.connect(self.agent_panel.add_system_message)

        self.pages.addWidget(self.dashboard)
        self.pages.addWidget(jobs)
        self.pages.addWidget(mock_interview)
        self.pages.currentChanged.connect(self._update_agent_page_context)

        navigation = [
            ("投递状态", "grid", 0),
            ("推荐岗位", "search", 1),
            ("模拟面试", "chat", 2),
        ]
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[int, QPushButton] = {}
        for label, icon_name, index in navigation:
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setIcon(_nav_icon(icon_name))
            button.setIconSize(QSize(18, 18))
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, page=index, nav_button=button: self._navigate_to(
                    page, nav_button
                )
            )
            self.nav_group.addButton(button)
            self.nav_buttons[index] = button
            sidebar_layout.addWidget(button)
            if index == 0:
                button.setChecked(True)

        sidebar_layout.addStretch()
        self.agent_panel.idle.connect(self._refresh_after_agent)
        environment = QLabel("服务端模式")
        environment.setToolTip("岗位搜索需要 BOSS 登录；邮箱与飞书需要配置。")
        environment.setObjectName("EnvironmentBadge")
        environment.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(environment)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setObjectName("ContentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(5)
        self.content_splitter.addWidget(self.pages)
        self.content_splitter.addWidget(self.agent_panel)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.setSizes([1080, 370])
        self._update_agent_page_context(self.pages.currentIndex())

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.content_splitter, 1)

    def _navigate_to(self, page: int, nav_button: QPushButton) -> None:
        current_page = self.pages.currentIndex()
        if page == current_page:
            nav_button.setChecked(True)
            return
        if current_page == 0 and not self.dashboard.resolve_pending_changes("切换页面"):
            self.nav_buttons[current_page].setChecked(True)
            return
        self.pages.setCurrentIndex(page)
        nav_button.setChecked(True)

    def _update_agent_page_context(self, page: int) -> None:
        page_context = self.PAGE_CONTEXT_BY_INDEX.get(page, "applications")
        self.agent_panel.set_page_context(page_context)
        show_agent = page != 2
        self.agent_panel.setVisible(show_agent)
        if show_agent:
            self.content_splitter.setSizes([1080, 370])

    def _refresh_after_agent(self) -> None:
        """刷新对话产生的业务变更，不丢弃表格中尚未保存的本地编辑。"""
        if self._closing_after_agent or self.dashboard.has_pending_changes:
            return
        try:
            self.dashboard.refresh()
        except Exception:
            self.dashboard.integration_notice.setText("表格刷新失败，请检查服务端连接后重试。")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.dashboard.resolve_pending_changes("关闭应用"):
            runners = [self.dashboard.runner, self.jobs_page.runner, self.mock_page.runner]
            self.dashboard._poll_timer.stop()
            if self.agent_panel.is_busy or any(runner.busy for runner in runners):
                if not self._closing_after_agent:
                    self._closing_after_agent = True
                    self.agent_panel.idle.connect(self.close)
                    for runner in runners:
                        runner.idle.connect(self.close)
                for runner in runners:
                    runner.cancel()
                self.agent_panel.cancel()
                event.ignore()
                return
            event.accept()
        else:
            event.ignore()


def _nav_icon(kind: str) -> QIcon:
    """创建线性小图标，分别提供普通状态和紫色选中状态。"""

    icon = QIcon()
    variants = (
        (QColor("#9894A5"), QIcon.Mode.Normal, QIcon.State.Off),
        (QColor("#8652E8"), QIcon.Mode.Normal, QIcon.State.On),
        (QColor("#8652E8"), QIcon.Mode.Active, QIcon.State.Off),
        (QColor("#8652E8"), QIcon.Mode.Active, QIcon.State.On),
    )
    for color, mode, state in variants:
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(
            QPen(
                color,
                1.8,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        if kind == "grid":
            for x, y in ((4, 4), (14, 4), (4, 14), (14, 14)):
                painter.drawRoundedRect(x, y, 6, 6, 1.4, 1.4)
        elif kind == "search":
            painter.drawEllipse(4, 4, 12, 12)
            painter.drawLine(15, 15, 20, 20)
        else:
            painter.drawRoundedRect(3, 4, 18, 14, 3, 3)
            painter.drawLine(7, 9, 17, 9)
            painter.drawLine(7, 13, 14, 13)
            painter.drawLine(8, 18, 6, 21)
        painter.end()
        icon.addPixmap(pixmap, mode, state)
    return icon
