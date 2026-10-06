from __future__ import annotations

from html import escape
import asyncio
from contextlib import aclosing
import re
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QEvent, QSize, Qt, QThread, Signal
from PySide6.QtGui import QKeyEvent, QTextDocumentFragment
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
)

from client.api.base import ApiClient
from client.ui.icons import app_icon
from client.ui.widgets.api_task import TaskRunner
from client.ui.widgets.glass import soft_shadow


class ChatWorker(QThread):
    """在 Qt 界面线程之外执行可取消的网络读写。"""

    chunk_received = Signal(dict)
    completed = Signal()
    failed = Signal(str)

    def __init__(self, api: ApiClient, messages: list[dict], metadata: dict, parent=None):
        """启动工作线程前保存接口客户端、对话历史和页面元数据。"""
        super().__init__(parent)
        self.api = api
        self.request_messages = messages
        self.metadata = metadata
        self.cancelled = Event()
        self.loop = None
        self.task = None

    def run(self) -> None:
        """创建工作线程的事件循环，并将失败转换为 Qt 信号。"""
        try:
            asyncio.run(self._receive())
            if not self.cancelled.is_set():
                self.completed.emit()
            else:
                self.failed.emit("已停止生成；本次回复未加入对话历史。")
        except asyncio.CancelledError:
            self.failed.emit("已停止生成；本次回复未加入对话历史。")
        except Exception as exc:
            self.failed.emit(str(exc))

    async def _receive(self) -> None:
        """转发 SSE 响应块，同时保留任务引用以便立即取消。"""
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        if self.cancelled.is_set():
            raise asyncio.CancelledError
        async with aclosing(self.api.stream_chat_completion(
            self.request_messages, metadata=self.metadata,
        )) as chunks:
            async for chunk in chunks:
                self.chunk_received.emit(chunk)

    def cancel(self) -> None:
        """从界面线程安全地取消正在进行的 HTTP 读取。"""
        self.cancelled.set()
        if self.loop and self.task:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass  # 工作线程已经关闭了它的事件循环。


class AgentInput(QPlainTextEdit):
    """支持回车发送、Shift+回车换行的 Agent 输入框。"""

    submit_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """没有按住 Shift 时将回车转换为发送信号。"""
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            event.accept()
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)


class AgentPanel(QFrame):
    idle = Signal()
    PAGE_CONTEXTS = {
        "applications": {
            "title": "投递进度",
            "subtitle": "查询状态、更新进度或询问下一步",
            "placeholder": "输入消息，例如：我目前有哪些面试？",
            "suggestions": ["查看待面试的公司", "梳理需要跟进的投递", "总结当前投递进度"],
        },
        "recommendations": {
            "title": "推荐岗位",
            "subtitle": "分析匹配度、JD 和投递优先级",
            "placeholder": "输入消息，例如：哪个岗位最值得优先投递？",
            "suggestions": ["哪些岗位更适合我？", "分析岗位的技术要求", "帮我安排投递优先级"],
        },
        "mock_interview": {
            "title": "模拟面试",
            "subtitle": "围绕目标公司和岗位进行面试训练",
            "placeholder": "输入消息，例如：先从 Java 基础开始面试",
            "suggestions": ["帮我制定面试准备计划", "梳理项目亮点", "从 Java 基础开始练习"],
        },
    }

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self._histories = {page: [] for page in self.PAGE_CONTEXTS}
        self._conversation_ids = {page: uuid4().hex for page in self.PAGE_CONTEXTS}
        self._transcript = [{"kind": "agent", "content": "你好，可以查询当前投递状态，也可以交流岗位选择和面试准备。", "label": "Agent"}]
        self._worker: ChatWorker | None = None
        self._reply = ""
        self._pending_page = "applications"
        self._pending_message = ""
        self._finish_reason = None
        self._email_candidates: dict[str, dict] = {}
        self.page_context = "applications"
        self.setObjectName("AgentPanel")
        self.setMinimumWidth(320)
        self.setMaximumWidth(720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 24, 22, 22)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        title_group = QVBoxLayout()
        title_group.setSpacing(2)
        title = QLabel("Agent 助手")
        title.setObjectName("AgentTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("ContextBadge")
        self.subtitle.setWordWrap(True)
        online = self.status_label = QLabel("● 就绪")
        online.setObjectName("OnlineLabel")
        title_group.addWidget(title)
        heading.addLayout(title_group)
        heading.addStretch()
        heading.addWidget(online, 0, Qt.AlignmentFlag.AlignTop)

        self.messages = QTextBrowser()
        self.messages.setObjectName("AgentMessages")
        self.messages.setOpenExternalLinks(True)

        self.candidate_runner = TaskRunner(api, self)
        self.candidate_runner.failed.connect(self._candidate_failed)
        self.candidate_runner.idle.connect(self._candidate_idle)

        self.candidate_review = QFrame()
        self.candidate_review.setObjectName("EmailCandidateReview")
        review_layout = QVBoxLayout(self.candidate_review)
        review_layout.setContentsMargins(14, 12, 14, 12)
        review_layout.setSpacing(8)
        review_heading = QHBoxLayout()
        review_title = QLabel("待创建投递")
        review_title.setObjectName("EmailCandidateTitle")
        self.candidate_count = QLabel()
        self.candidate_count.setObjectName("EmailCandidateCount")
        review_heading.addWidget(review_title)
        review_heading.addStretch()
        review_heading.addWidget(self.candidate_count)
        review_layout.addLayout(review_heading)
        review_hint = QLabel("邮件中已识别到招聘事项，但本地没有对应记录。勾选确认后再创建。")
        review_hint.setObjectName("EmailCandidateHint")
        review_hint.setWordWrap(True)
        review_layout.addWidget(review_hint)

        self.candidate_table = QTableWidget(0, 6)
        self.candidate_table.setObjectName("EmailCandidateTable")
        self.candidate_table.setHorizontalHeaderLabels(
            ["选择", "公司", "岗位", "Base", "状态", "时间"]
        )
        self.candidate_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.candidate_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.candidate_table.verticalHeader().setVisible(False)
        self.candidate_table.verticalHeader().setDefaultSectionSize(38)
        self.candidate_table.setShowGrid(False)
        header = self.candidate_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.candidate_table.setColumnWidth(0, 46)
        self.candidate_table.itemChanged.connect(self._candidate_selection_changed)
        review_layout.addWidget(self.candidate_table)

        review_actions = QHBoxLayout()
        self.candidate_feedback = QLabel("")
        self.candidate_feedback.setObjectName("EmailCandidateFeedback")
        self.candidate_feedback.setWordWrap(True)
        self.candidate_create_button = QPushButton("创建选中记录")
        self.candidate_create_button.setObjectName("PrimaryButton")
        self.candidate_create_button.setEnabled(False)
        self.candidate_create_button.clicked.connect(self._create_selected_candidates)
        review_actions.addWidget(self.candidate_feedback, 1)
        review_actions.addWidget(self.candidate_create_button)
        review_layout.addLayout(review_actions)
        self.candidate_review.hide()

        self.welcome = QFrame()
        welcome_layout = QVBoxLayout(self.welcome)
        welcome_layout.setContentsMargins(0, 0, 0, 0)
        welcome_layout.setSpacing(12)
        welcome_layout.addStretch(2)
        mark = self.welcome_mark = QLabel()
        mark.setObjectName("AssistantMark")
        mark.setFixedSize(64, 64)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setPixmap(app_icon("spark", "#987BD6").pixmap(QSize(32, 32)))
        soft_shadow(mark, blur=22, opacity=20, offset=6)
        welcome_layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignLeft)
        welcome_layout.addSpacing(6)
        welcome_title = QLabel("准备好下一步")
        welcome_title.setObjectName("WelcomeTitle")
        welcome_layout.addWidget(welcome_title)
        welcome_detail = self.welcome_detail = QLabel("梳理投递进度，找到值得关注的机会。")
        welcome_detail.setObjectName("WelcomeSubtitle")
        welcome_detail.setWordWrap(True)
        welcome_layout.addWidget(welcome_detail)
        welcome_layout.addSpacing(12)
        self.suggestion_buttons = []
        for icon in ("calendar", "search", "chat"):
            button = QPushButton()
            button.setObjectName("SuggestionButton")
            button.setIcon(app_icon(icon))
            button.setIconSize(QSize(17, 17))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, source=button: self._use_suggestion(source.text()))
            self.suggestion_buttons.append(button)
            welcome_layout.addWidget(button)
        welcome_layout.addStretch(3)

        self.input = AgentInput()
        self.input.setObjectName("AgentInput")
        self.input.setFixedHeight(88)
        self.input.setAccessibleName("向助手提问")
        self.input.submit_requested.connect(self._submit_from_input)

        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("AgentSendButton")
        self.send_button.clicked.connect(self._send_message)

        action_row = QHBoxLayout()
        input_hint = QLabel("Enter 发送")
        input_hint.setToolTip("Shift + Enter 换行")
        input_hint.setObjectName("InputHint")
        action_row.addWidget(input_hint)
        action_row.addStretch()
        action_row.addWidget(self.send_button)

        self.composer = QFrame()
        self.composer.setObjectName("Composer")
        composer_layout = QVBoxLayout(self.composer)
        composer_layout.setContentsMargins(12, 10, 12, 10)
        composer_layout.setSpacing(4)
        composer_layout.addWidget(self.input)
        composer_layout.addLayout(action_row)
        self.input.installEventFilter(self)

        layout.addLayout(heading)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.welcome, 1)
        layout.addWidget(self.messages, 1)
        layout.addWidget(self.candidate_review)
        layout.addWidget(self.composer)
        self._render_messages()
        self.set_page_context(self.page_context)

    def resizeEvent(self, event) -> None:
        compact = self.height() < 650
        self.welcome_mark.setVisible(not compact)
        self.welcome_detail.setVisible(not compact)
        super().resizeEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.input and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.composer.setProperty("focused", event.type() == QEvent.Type.FocusIn)
            self.composer.style().unpolish(self.composer)
            self.composer.style().polish(self.composer)
            self.composer.update()
        return super().eventFilter(watched, event)

    def _use_suggestion(self, text: str) -> None:
        """Insert a suggested question without sending or overwriting a draft."""
        if self.input.toPlainText().strip():
            self.input.appendPlainText(text)
        else:
            self.input.setPlainText(text)
        self.input.setFocus()

    def set_page_context(self, page_context: str) -> None:
        context = self.PAGE_CONTEXTS.get(page_context)
        if context is None:
            return
        self.page_context = page_context
        self.subtitle.setText(f"当前页面：{context['title']}")
        self.subtitle.setToolTip(context["subtitle"])
        self.input.setPlaceholderText(context["placeholder"])
        for button, suggestion in zip(self.suggestion_buttons, context["suggestions"]):
            button.setText(suggestion)

    def add_system_message(self, content: str) -> None:
        """显示本地页面提示，不将其加入模型对话历史。"""
        self._transcript.append({"kind": "agent", "content": content, "label": "系统"})
        self._render_messages()

    @property
    def is_busy(self) -> bool:
        """判断请求是否仍占用工作线程及其 HTTP 连接。"""
        return self._worker is not None or self.candidate_runner.busy

    def cancel(self) -> None:
        """停止当前生成，供停止按钮和窗口关闭流程共用。"""
        if self._worker:
            self._worker.cancel()
            self.send_button.setText("正在停止…")
            self.send_button.setEnabled(False)
        if self.candidate_runner.busy:
            self.candidate_runner.cancel()

    def _send_message(self) -> None:
        """记录当前页面，并启动后台流式请求。"""
        if self.candidate_runner.busy:
            return
        if self._worker is not None:
            self.cancel()
            return
        message = self.input.toPlainText().strip()
        if not message:
            return
        self.input.clear()
        self._pending_page = self.page_context
        self._pending_message = message
        self._reply = ""
        self._finish_reason = None
        self._transcript.append({"kind": "user", "content": message, "label": "我"})
        self._reply_item = {"kind": "agent", "content": "正在处理…", "label": f"Agent · {self.PAGE_CONTEXTS[self.page_context]['title']}"}
        self._transcript.append(self._reply_item)
        self._render_messages()
        messages = [*self._histories[self.page_context], {"role": "user", "content": message}]
        self._worker = ChatWorker(self.api, messages, {
            "page_context": self.page_context,
            "conversation_id": self._conversation_ids[self.page_context],
        }, self)
        self._worker.chunk_received.connect(self._on_chunk)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_finished)
        self.send_button.setText("停止生成")
        self.status_label.setText("● 处理中")
        self._worker.start()

    def _submit_from_input(self) -> None:
        """回车仅在空闲时发送，避免生成过程中误触导致取消。"""
        if not self.is_busy:
            self._send_message()

    def _on_chunk(self, chunk: dict) -> None:
        """仅追加助手回复文本，不将模型推理内容显示到界面。"""
        candidates = chunk.get("app_data", {}).get("email_creation_candidates", [])
        if candidates:
            self.show_email_candidates(candidates)
        for choice in chunk.get("choices", []):
            self._reply += choice.get("delta", {}).get("content") or ""
            self._finish_reason = choice.get("finish_reason") or self._finish_reason
        self._reply_item["content"] = self._reply or "正在处理…"
        self._render_messages()

    def _on_completed(self) -> None:
        """将成功的一轮问答写入请求发起时所在页面的对话历史。"""
        if self._worker and self._worker.cancelled.is_set():
            self._on_failed("已停止生成；本次回复未加入对话历史。")
            return
        if not self._reply:
            self._on_failed("Agent 未返回正文，请重试。")
            return
        self._histories[self._pending_page].extend([
            {"role": "user", "content": self._pending_message},
            {"role": "assistant", "content": self._reply},
        ])
        if self._finish_reason == "length":
            self.add_system_message("本次回复达到长度限制，可以发送“继续”。")

    def _on_failed(self, message: str) -> None:
        """保留已显示的部分回复，并恢复失败的输入以便重试。"""
        self._reply_item["content"] = ((self._reply + "\n\n") if self._reply else "") + message
        if not self.input.toPlainText().strip():
            self.input.setPlainText(self._pending_message)
        self._render_messages()

    def _on_finished(self) -> None:
        """先释放已停止的线程，再通知窗口可以关闭。"""
        worker = self._worker
        self._worker = None
        if worker:
            worker.deleteLater()
        self.send_button.setEnabled(True)
        self.send_button.setText("发送")
        self.status_label.setText("● 就绪")
        if not self.candidate_runner.busy:
            self.idle.emit()

    def show_email_candidates(self, candidates: list[dict]) -> None:
        """显示服务端保存的待创建邮件候选项，不信任前端自行构造业务字段。"""
        for candidate in candidates:
            candidate_id = candidate.get("id")
            if candidate_id:
                self._email_candidates[candidate_id] = dict(candidate)
        if not self._email_candidates:
            return
        if len(self._transcript) == 1:
            self._transcript.append({
                "kind": "agent",
                "content": "邮件中发现本地尚未记录的招聘事项，请在下表确认是否创建。",
                "label": "系统",
            })
            self._render_messages()
        self._render_candidate_table()

    def _render_candidate_table(self) -> None:
        """根据待确认候选项重建审核表，默认不替用户勾选。"""
        rows = list(self._email_candidates.values())
        self.candidate_table.blockSignals(True)
        self.candidate_table.setRowCount(len(rows))
        for row, candidate in enumerate(rows):
            selector = QTableWidgetItem("")
            selector.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            selector.setCheckState(Qt.CheckState.Unchecked)
            selector.setData(Qt.ItemDataRole.UserRole, candidate["id"])
            self.candidate_table.setItem(row, 0, selector)
            values = (
                candidate.get("company_name") or "待确认",
                candidate.get("position_name") or "待确认",
                candidate.get("base_location") or "待确认",
                candidate.get("current_status") or "待确认",
                _display_datetime(candidate.get("interview_time")),
            )
            for column, value in enumerate(values, 1):
                item = QTableWidgetItem(value)
                item.setToolTip(
                    candidate.get("source_subject") or value
                    if column in {1, 2}
                    else value
                )
                self.candidate_table.setItem(row, column, item)
        self.candidate_table.blockSignals(False)
        visible_rows = min(max(len(rows), 1), 5)
        self.candidate_table.setFixedHeight(31 + visible_rows * 38 + 4)
        self.candidate_count.setText(f"{len(rows)} 条")
        self.candidate_feedback.clear()
        self.candidate_review.show()
        self._candidate_selection_changed()

    def _selected_candidate_ids(self) -> list[str]:
        return [
            self.candidate_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in range(self.candidate_table.rowCount())
            if self.candidate_table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]

    def _candidate_selection_changed(self, _item=None) -> None:
        count = len(self._selected_candidate_ids())
        self.candidate_create_button.setEnabled(count > 0 and not self.candidate_runner.busy)
        self.candidate_create_button.setText(
            f"创建选中记录（{count}）" if count else "创建选中记录"
        )

    def _create_selected_candidates(self) -> None:
        candidate_ids = self._selected_candidate_ids()
        if not candidate_ids or self.is_busy:
            return
        self.candidate_feedback.setText("正在创建…")
        self.candidate_create_button.setEnabled(False)
        self.send_button.setEnabled(False)
        self.status_label.setText("● 保存中")
        self.candidate_runner.start(
            "create_email_candidates",
            self._candidate_created,
            candidate_ids=candidate_ids,
        )

    def _candidate_created(self, result: dict) -> None:
        resolved = {
            item["id"]
            for key in ("created", "already_created")
            for item in result.get(key, [])
        }
        for candidate_id in resolved:
            self._email_candidates.pop(candidate_id, None)
        failures = result.get("failed", [])
        created_count = len(result.get("created", []))
        existing_count = len(result.get("already_created", []))
        parts = []
        if created_count:
            parts.append(f"已创建 {created_count} 条投递记录")
        if existing_count:
            parts.append(f"已有 {existing_count} 条记录")
        if failures:
            parts.append(f"{len(failures)} 条创建失败")
        message = "，".join(parts) + "。"
        self.add_system_message(message)
        if self._email_candidates:
            self._render_candidate_table()
            self.candidate_feedback.setText(
                failures[0].get("reason", "部分记录创建失败，请检查。")
                if failures else ""
            )
        else:
            self.candidate_review.hide()

    def _candidate_failed(self, message: str) -> None:
        self.candidate_feedback.setText(message)

    def _candidate_idle(self) -> None:
        self.send_button.setEnabled(True)
        self.status_label.setText("● 就绪")
        self._candidate_selection_changed()
        if self._worker is None:
            self.idle.emit()

    def _render_messages(self) -> None:
        """以 Markdown 渲染可见对话，不与各页面发送给模型的历史混用。"""
        has_conversation = len(self._transcript) > 1
        self.welcome.setVisible(not has_conversation)
        self.messages.setVisible(has_conversation)
        body = "".join(
            _user_bubble(item["content"]) if item["kind"] == "user"
            else _agent_bubble(item["content"], item["label"])
            for item in self._transcript
        )
        self.messages.setHtml(
            "<style>"
            "a{color:#8061BE;text-decoration:none;}"
            "code{font-family:'Cascadia Code','Consolas';color:#414145;background:#ECEEF2;}"
            "pre{font-family:'Cascadia Code','Consolas';color:#414145;background:#F5F5F7;"
            "border:1px solid #E5E5EA;padding:9px;}"
            "blockquote{color:#6E6E73;border-left:3px solid #D5C5EE;margin-left:2px;padding-left:9px;}"
            "</style>" + body
        )
        self.messages.verticalScrollBar().setValue(
            self.messages.verticalScrollBar().maximum()
        )


def _agent_bubble(content: str, label: str = "Agent") -> str:
    """生成无厚重气泡的助手消息，正文支持安全的 Markdown 子集。"""
    return (
        "<table width='100%' cellspacing='0' cellpadding='5'>"
        "<tr><td width='24' valign='top'><span style='color:#987BD6;font-size:16px'>✦</span></td>"
        f"<td valign='top'><span style='color:#1D1D1F;font-weight:700'>{escape(label)}</span>"
        f"<div style='color:#414145'>{_markdown_fragment(content)}</div></td></tr></table><br>"
    )


def _user_bubble(content: str) -> str:
    """生成靠右的浅灰用户消息卡片，并保留 Markdown 基础格式。"""
    return (
        "<table width='86%' align='right' cellspacing='0' cellpadding='11' "
        "style='background:#EEE7F9;border:0;'>"
        f"<tr><td><div style='color:#1D1D1F'>{_markdown_fragment(content)}</div></td></tr></table><br>"
    )


def _markdown_fragment(content: str) -> str:
    """将 Markdown 转为可嵌入消息卡片的安全 Qt 富文本片段。

    参数:
        content: Agent 或用户输入的 Markdown 文本。

    返回值:
        已转义原始 HTML、保留 Markdown 格式的正文 HTML。
    """
    fragments: list[str] = []
    for kind, payload in _split_markdown_tables(content):
        if kind == "table":
            headers, rows = payload
            fragments.append(_record_cards(headers, rows))
        elif payload:
            fragments.append(_qt_markdown_fragment(payload))
    return "".join(fragments)


def _qt_markdown_fragment(content: str) -> str:
    """使用 Qt 渲染普通 Markdown；表格由上层转换成适合窄栏的卡片。"""
    safe_markdown = escape(content, quote=False)
    document_html = QTextDocumentFragment.fromMarkdown(safe_markdown).toHtml()
    body = re.search(r"<body[^>]*>(.*)</body>", document_html, re.S)
    if body is None:
        return escape(content).replace("\n", "<br>")
    return body.group(1).replace("<!--StartFragment-->", "").replace("<!--EndFragment-->", "")


def _split_markdown_tables(content: str) -> list[tuple[str, object]]:
    """切分正文中的标准 Markdown 表格，避免 Qt 不支持时显示竖线原文。"""
    lines = content.splitlines()
    result: list[tuple[str, object]] = []
    text_lines: list[str] = []
    index = 0
    while index < len(lines):
        headers = _markdown_table_cells(lines[index])
        divider = (
            _markdown_table_cells(lines[index + 1])
            if index + 1 < len(lines) else None
        )
        if not (
            headers and divider and len(headers) == len(divider)
            and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in divider)
        ):
            text_lines.append(lines[index])
            index += 1
            continue

        rows: list[list[str]] = []
        cursor = index + 2
        while cursor < len(lines):
            cells = _markdown_table_cells(lines[cursor])
            if cells is None:
                break
            rows.append((cells + [""] * len(headers))[:len(headers)])
            cursor += 1
        if not rows:
            text_lines.extend(lines[index:index + 2])
            index += 2
            continue

        if text_lines:
            result.append(("text", "\n".join(text_lines)))
            text_lines = []
        result.append(("table", (headers, rows)))
        index = cursor

    if text_lines:
        result.append(("text", "\n".join(text_lines)))
    return result


def _markdown_table_cells(line: str) -> list[str] | None:
    """解析一行简单 Markdown 表格，不把普通正文中的单个竖线视为表格。"""
    stripped = line.strip()
    if stripped.count("|") < 2:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells = [cell.strip() for cell in stripped.split("|")]
    return cells if len(cells) >= 2 else None


def _record_cards(headers: list[str], rows: list[list[str]]) -> str:
    """将横向业务表格转换为适合 Agent 窄侧栏的纵向记录卡片。"""
    company_index = _header_index(headers, {"公司", "企业", "单位", "company"})
    position_index = _header_index(headers, {"岗位", "职位", "应聘岗位", "role", "position"})
    status_index = _header_index(headers, {"状态", "当前状态", "进度", "status"})
    id_index = _header_index(headers, {"id", "编号", "序号"})
    cards: list[str] = ["<div style='margin:7px 0 11px 0;'>"]

    for row in rows:
        fallback_indexes = [
            index for index, value in enumerate(row)
            if value and index not in {id_index, status_index}
        ]
        title_index = company_index if company_index is not None else (
            fallback_indexes[0] if fallback_indexes else None
        )
        title = row[title_index] if title_index is not None else "未命名记录"
        subtitle = row[position_index] if position_index is not None else ""
        status = row[status_index] if status_index is not None else ""
        record_id = row[id_index] if id_index is not None else ""
        excluded = {title_index, position_index, status_index, id_index}
        details = [
            (header, row[index])
            for index, header in enumerate(headers)
            if index not in excluded and row[index]
        ]

        cards.append(
            "<table width='100%' cellspacing='0' cellpadding='0' "
            "style='margin:7px 0;background-color:#FAF8FD;border:1px solid #E2D8ED;'>"
            "<tr><td style='padding:10px 11px 8px 11px;'>"
            "<table width='100%' cellspacing='0' cellpadding='0'><tr>"
            "<td valign='top'>"
            f"<span style='color:#242128;font-size:14px;font-weight:700'>{escape(title)}</span>"
            + (
                f"<br><span style='color:#625C68;font-size:12px'>{escape(subtitle)}</span>"
                if subtitle and position_index != title_index else ""
            )
            + (
                f"<br><span style='color:#92889A;font-size:10px'>记录 #{escape(record_id)}</span>"
                if record_id else ""
            )
            + "</td>"
            + (
                "<td align='right' valign='top' style='padding-left:8px;'>"
                f"<span style='color:#7555B3;background-color:#EEE7F9;font-size:11px'>"
                f"&nbsp;{escape(status)}&nbsp;</span></td>"
                if status else ""
            )
            + "</tr></table>"
        )
        if details:
            cards.append("<table width='100%' cellspacing='0' cellpadding='2' style='margin-top:7px;'>")
            for label, value in details:
                cards.append(
                    "<tr>"
                    f"<td width='74' valign='top' style='color:#8B8291;font-size:11px'>{escape(label)}</td>"
                    f"<td valign='top' style='color:#454148;font-size:11px'>{escape(value)}</td>"
                    "</tr>"
                )
            cards.append("</table>")
        cards.append("</td></tr></table>")

    cards.append("</div>")
    return "".join(cards)


def _header_index(headers: list[str], names: set[str]) -> int | None:
    """按去空格、忽略英文大小写后的字段名寻找列位置。"""
    normalized_names = {name.replace(" ", "").lower() for name in names}
    for index, header in enumerate(headers):
        if header.replace(" ", "").lower() in normalized_names:
            return index
    return None


def _display_datetime(value: str | None) -> str:
    """把服务端 ISO 时间压缩成审核表中的本地可读格式。"""
    if not value:
        return "待确认"
    return value.replace("T", " ", 1)[:16]
