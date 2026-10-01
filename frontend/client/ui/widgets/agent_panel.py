from __future__ import annotations

from html import escape
import asyncio
from contextlib import aclosing
import re
from threading import Event
from uuid import uuid4

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QKeyEvent, QTextDocumentFragment
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from client.api.base import ApiClient


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
            "title": "投递状态",
            "subtitle": "查询状态、更新进度或询问下一步",
            "placeholder": "输入消息，例如：我目前有哪些面试？",
        },
        "recommendations": {
            "title": "推荐岗位",
            "subtitle": "分析匹配度、JD 和投递优先级",
            "placeholder": "输入消息，例如：哪个岗位最值得优先投递？",
        },
        "mock_interview": {
            "title": "模拟面试",
            "subtitle": "围绕目标公司和岗位进行面试训练",
            "placeholder": "输入消息，例如：先从 Java 基础开始面试",
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
        self.page_context = "applications"
        self.setObjectName("AgentPanel")
        self.setMinimumWidth(320)
        self.setMaximumWidth(720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 22, 20, 20)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        title_group = QVBoxLayout()
        title_group.setSpacing(2)
        title = QLabel("Agent 助手")
        title.setObjectName("AgentTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("MutedLabel")
        self.subtitle.setWordWrap(True)
        online = QLabel("● 就绪")
        online.setObjectName("OnlineLabel")
        title_group.addWidget(title)
        title_group.addWidget(self.subtitle)
        heading.addLayout(title_group)
        heading.addStretch()
        heading.addWidget(online, 0, Qt.AlignmentFlag.AlignTop)

        self.messages = QTextBrowser()
        self.messages.setObjectName("AgentMessages")
        self.messages.setOpenExternalLinks(True)
        self._render_messages()

        self.input = AgentInput()
        self.input.setObjectName("AgentInput")
        self.input.setFixedHeight(88)
        self.input.submit_requested.connect(self._submit_from_input)

        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("AgentSendButton")
        self.send_button.clicked.connect(self._send_message)

        action_row = QHBoxLayout()
        input_hint = QLabel("Enter 发送  ·  Shift + Enter 换行")
        input_hint.setObjectName("InputHint")
        action_row.addWidget(input_hint)
        action_row.addStretch()
        action_row.addWidget(self.send_button)

        layout.addLayout(heading)
        layout.addWidget(self.messages, 1)
        layout.addWidget(self.input)
        layout.addLayout(action_row)
        self.set_page_context(self.page_context)

    def set_page_context(self, page_context: str) -> None:
        context = self.PAGE_CONTEXTS.get(page_context)
        if context is None:
            return
        self.page_context = page_context
        self.subtitle.setText(f"当前页面：{context['title']} · {context['subtitle']}")
        self.input.setPlaceholderText(context["placeholder"])

    def add_system_message(self, content: str) -> None:
        """显示本地页面提示，不将其加入模型对话历史。"""
        self._transcript.append({"kind": "agent", "content": content, "label": "系统"})
        self._render_messages()

    @property
    def is_busy(self) -> bool:
        """判断请求是否仍占用工作线程及其 HTTP 连接。"""
        return self._worker is not None

    def cancel(self) -> None:
        """停止当前生成，供停止按钮和窗口关闭流程共用。"""
        if self._worker:
            self._worker.cancel()
            self.send_button.setText("正在停止…")
            self.send_button.setEnabled(False)

    def _send_message(self) -> None:
        """记录当前页面，并启动后台流式请求。"""
        if self.is_busy:
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
        self._worker.start()

    def _submit_from_input(self) -> None:
        """回车仅在空闲时发送，避免生成过程中误触导致取消。"""
        if not self.is_busy:
            self._send_message()

    def _on_chunk(self, chunk: dict) -> None:
        """仅追加助手回复文本，不将模型推理内容显示到界面。"""
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
        self.idle.emit()

    def _render_messages(self) -> None:
        """以 Markdown 渲染可见对话，不与各页面发送给模型的历史混用。"""
        body = "".join(
            _user_bubble(item["content"]) if item["kind"] == "user"
            else _agent_bubble(item["content"], item["label"])
            for item in self._transcript
        )
        self.messages.setHtml(
            "<style>"
            "a{color:#6f42c9;text-decoration:none;}"
            "code{font-family:'Cascadia Code','Consolas';color:#44365a;background:#f1eef5;}"
            "pre{font-family:'Cascadia Code','Consolas';color:#44365a;background:#f5f3f7;"
            "border:1px solid #e7e3eb;padding:9px;}"
            "blockquote{color:#706a78;border-left:3px solid #c9b7ee;margin-left:2px;padding-left:9px;}"
            "</style>" + body
        )
        self.messages.verticalScrollBar().setValue(
            self.messages.verticalScrollBar().maximum()
        )


def _agent_bubble(content: str, label: str = "Agent") -> str:
    """生成无厚重气泡的助手消息，正文支持安全的 Markdown 子集。"""
    return (
        "<table width='100%' cellspacing='0' cellpadding='5'>"
        "<tr><td width='24' valign='top'><span style='color:#7c4ddb;font-size:16px'>✦</span></td>"
        f"<td valign='top'><span style='color:#28252d;font-weight:700'>{escape(label)}</span>"
        f"<div style='color:#514d57'>{_markdown_fragment(content)}</div></td></tr></table><br>"
    )


def _user_bubble(content: str) -> str:
    """生成靠右的浅灰用户消息卡片，并保留 Markdown 基础格式。"""
    return (
        "<table width='86%' align='right' cellspacing='0' cellpadding='11' "
        "style='background:#efedf1;border:1px solid #e3e0e6;'>"
        f"<tr><td><div style='color:#343139'>{_markdown_fragment(content)}</div></td></tr></table><br>"
    )


def _markdown_fragment(content: str) -> str:
    """将 Markdown 转为可嵌入消息卡片的安全 Qt 富文本片段。

    参数:
        content: Agent 或用户输入的 Markdown 文本。

    返回值:
        已转义原始 HTML、保留 Markdown 格式的正文 HTML。
    """
    safe_markdown = escape(content, quote=False)
    document_html = QTextDocumentFragment.fromMarkdown(safe_markdown).toHtml()
    body = re.search(r"<body[^>]*>(.*)</body>", document_html, re.S)
    if body is None:
        return escape(content).replace("\n", "<br>")
    return body.group(1).replace("<!--StartFragment-->", "").replace("<!--EndFragment-->", "")
