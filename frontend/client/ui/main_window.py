from __future__ import annotations

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSplitter, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from client.api.base import ApiClient
from client.styles import APP_STYLE
from client.ui.icons import app_icon
from client.ui.pages import DashboardPage, JobsPage, MockInterviewPage
from client.ui.widgets import AgentPanel
from client.ui.widgets.glass import AmbientBackground, soft_shadow


class MainWindow(QMainWindow):
    PAGE_CONTEXT_BY_INDEX = {0: "applications", 1: "recommendations", 2: "mock_interview"}

    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api
        self._closing_after_agent = False
        self.setWindowTitle("Interview Assistant")
        self.resize(1680, 1020)
        self.setMinimumSize(1180, 720)
        self.setWindowIcon(app_icon("spark", "#9273D5"))
        self.setStyleSheet(APP_STYLE)
        self._build_ui()

    def _build_ui(self) -> None:
        root = AmbientBackground()
        root.setObjectName("AppRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(32, 28, 32, 28)
        self.setCentralWidget(root)

        shell = QFrame()
        shell.setObjectName("AppShell")
        soft_shadow(shell, blur=60, opacity=32, offset=16)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(24, 18, 24, 24)
        shell_layout.setSpacing(20)
        root_layout.addWidget(shell)

        topbar = QFrame()
        topbar.setObjectName("Topbar")
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(4, 0, 4, 14)
        topbar_layout.setSpacing(12)
        mark = QLabel()
        mark.setFixedSize(38, 38)
        mark.setPixmap(app_icon("spark", "#9273D5").pixmap(QSize(29, 29)))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        topbar_layout.addWidget(mark)
        brand = QLabel("秋招助手")
        brand.setObjectName("BrandText")
        topbar_layout.addWidget(brand)
        topbar_layout.addStretch()

        nav = QFrame()
        nav.setObjectName("Navigation")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(5, 5, 5, 5)
        nav_layout.setSpacing(5)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[int, QPushButton] = {}
        for index, (label, kind) in enumerate((("投递进度", "grid"), ("推荐岗位", "search"), ("模拟面试", "chat"))):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setIcon(app_icon(kind))
            button.setIconSize(QSize(16, 16))
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, page=index, source=button: self._navigate_to(page, source))
            self.nav_group.addButton(button)
            self.nav_buttons[index] = button
            nav_layout.addWidget(button)
            if index == 0:
                button.setChecked(True)
        topbar_layout.addWidget(nav)
        topbar_layout.addStretch()
        date = QLabel(QDate.currentDate().toString("yyyy / MM / dd"))
        date.setObjectName("MutedLabel")
        topbar_layout.addWidget(date)
        topbar_layout.addSpacing(12)
        workspace = QLabel("个人工作台")
        workspace.setObjectName("WorkspaceTitle")
        topbar_layout.addWidget(workspace)
        avatar = QLabel("我")
        avatar.setObjectName("ProfileBadge")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(32, 32)
        topbar_layout.addWidget(avatar)
        shell_layout.addWidget(topbar)

        self.pages = QStackedWidget()
        self.pages.setObjectName("PageStack")
        self.pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.agent_panel = AgentPanel(self.api)
        self.dashboard = DashboardPage(self.api)
        self.jobs_page = JobsPage(self.api)
        self.mock_page = MockInterviewPage(self.api)
        self.dashboard.event_message.connect(self.agent_panel.add_system_message)
        self.dashboard.email_candidates.connect(self.agent_panel.show_email_candidates)
        self.jobs_page.event_message.connect(self.agent_panel.add_system_message)
        for page in (self.dashboard, self.jobs_page, self.mock_page):
            self.pages.addWidget(page)
        self.pages.currentChanged.connect(self._update_agent_page_context)
        self.agent_panel.idle.connect(self._refresh_after_agent)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setObjectName("ContentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(20)
        self.content_splitter.addWidget(self.pages)
        self.content_splitter.addWidget(self.agent_panel)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.setSizes([1190, 350])
        shell_layout.addWidget(self.content_splitter, 1)
        self._update_agent_page_context(0)

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
        self.agent_panel.set_page_context(self.PAGE_CONTEXT_BY_INDEX.get(page, "applications"))
        show_agent = page != 2
        self.agent_panel.setVisible(show_agent)
        if show_agent:
            self.content_splitter.setSizes([1190, 350])

    def _refresh_after_agent(self) -> None:
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
