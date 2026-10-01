from __future__ import annotations

from PySide6.QtCore import QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from client.api.base import ApiClient
from client.ui.widgets.api_task import TaskRunner


def _split_values(value: str) -> list[str]:
    return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]


class JobsPage(QWidget):
    event_message = Signal(str)

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.current_page = 1
        self.page_size = 2
        self.total_pages = 1
        self._search_filters = None
        self.runner = TaskRunner(api, self)
        self.runner.failed.connect(self._show_error)
        self.runner.idle.connect(self._ready)
        self._build_ui()
        self._load_jobs(cached_only=True)

    def _build_ui(self) -> None:
        self.setObjectName("PageSurface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        title = QLabel("推荐岗位")
        title.setObjectName("PageTitle")
        subtitle = QLabel("查看匹配度、岗位 JD 和原始投递链接")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        filter_frame = QFrame()
        filter_frame.setObjectName("Toolbar")
        filters = QHBoxLayout(filter_frame)
        filters.setContentsMargins(12, 9, 12, 9)
        self.city_input = QLineEdit("上海,杭州")
        self.city_input.setPlaceholderText("目标城市，用逗号分隔")
        self.tech_input = QLineEdit("Java,Spring Boot,MySQL")
        self.tech_input.setPlaceholderText("技术栈，用逗号分隔")
        self.keyword_input = QLineEdit("Java")
        self.keyword_input.setPlaceholderText("岗位关键词")
        search_button = self.search_button = QPushButton("重新匹配")
        search_button.setObjectName("PrimaryButton")
        search_button.clicked.connect(self.search_jobs)
        filters.addWidget(self.city_input)
        filters.addWidget(self.tech_input)
        filters.addWidget(self.keyword_input)
        filters.addWidget(search_button)
        layout.addWidget(filter_frame)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setObjectName("MutedLabel")
        layout.addWidget(self.notice)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 8, 0)
        self.list_layout.setSpacing(14)
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
        self._load_jobs(announce=True, refresh=True)

    def _load_jobs(self, announce: bool = False, refresh=False, cached_only=False) -> None:
        if refresh or self._search_filters is None:
            self._search_filters = {"cities": _split_values(self.city_input.text()),
                "tech_stack": _split_values(self.tech_input.text()), "keywords": _split_values(self.keyword_input.text())}
        self.search_button.setEnabled(False)
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.notice.setText("正在加载…" if cached_only else "正在获取岗位和分析 JD，请稍候…")
        self.runner.start("recommend_jobs", self._loaded,
            **self._search_filters,
            page=self.current_page,
            page_size=self.page_size,
            extensions={"refresh": refresh, "cached_only": cached_only},
        )

    def _loaded(self, result):
        """渲染服务端结果，失败时不使用演示数据替代。"""
        self.total_pages = result["total_pages"]
        self._render_jobs(result["items"])
        self.page_label.setText(
            f"第 {result['page']} / {result['total_pages']} 页 · 共 {result['total']} 个岗位"
        )
        self.previous_button.setEnabled(result["has_previous"])
        self.next_button.setEnabled(result["has_next"])
        self.notice.setText(result.get("message") or f"本次候选中共有 {result['total']} 个匹配岗位。")

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
        for job in jobs:
            self.list_layout.insertWidget(self.list_layout.count() - 1, self._create_card(job))

    def _create_card(self, job: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel(f"{job['company_name']} · {job['position_name']}")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        title.setObjectName("SectionTitle")
        score = QLabel(f"匹配度 {job['match_score']}%")
        score.setObjectName("ScoreBadge")
        top.addWidget(title)
        top.addStretch()
        top.addWidget(score)
        layout.addLayout(top)

        meta = QLabel(f"Base：{job['base_location']}    {job['jd_summary']}")
        meta.setObjectName("MutedLabel")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        reasons = QLabel("匹配点：" + "；".join(job["match_reasons"]))
        reasons.setObjectName("ReasonBox")
        reasons.setWordWrap(True)
        layout.addWidget(reasons)

        risks = QLabel("风险点：" + "；".join(job["risk_points"]))
        risks.setObjectName("RiskBox")
        risks.setWordWrap(True)
        layout.addWidget(risks)

        jd = QLabel(job["job_description"])
        jd.setTextFormat(Qt.TextFormat.PlainText)
        jd.setObjectName("JdBox")
        jd.setWordWrap(True)
        jd.setVisible(False)
        layout.addWidget(jd)

        actions = QHBoxLayout()
        details_button = QPushButton("展开 JD")
        details_button.setObjectName("SecondaryButton")
        details_button.clicked.connect(
            lambda _checked=False, label=jd, button=details_button: self._toggle_jd(label, button)
        )
        apply_button = QPushButton("去投递")
        apply_button.setObjectName("PrimaryButton")
        apply_button.clicked.connect(
            lambda _checked=False, url=job["job_url"]: QDesktopServices.openUrl(QUrl(url))
        )
        actions.addStretch()
        actions.addWidget(details_button)
        actions.addWidget(apply_button)
        layout.addLayout(actions)
        return card

    @staticmethod
    def _toggle_jd(label: QLabel, button: QPushButton) -> None:
        visible = not label.isVisible()
        label.setVisible(visible)
        button.setText("收起 JD" if visible else "展开 JD")
