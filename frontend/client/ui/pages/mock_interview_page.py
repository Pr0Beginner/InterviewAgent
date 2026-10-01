from __future__ import annotations

from html import escape

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from client.api.base import ApiClient
from client.ui.widgets.api_task import TaskRunner
from PySide6.QtCore import QSettings


class MockInterviewPage(QWidget):
    event_message = Signal(str)

    TARGET_COMPANIES = [
        "通用（不指定公司）",
        "阿里巴巴",
        "腾讯",
        "字节跳动",
        "美团",
        "京东",
        "百度",
        "网易",
        "拼多多",
        "小米",
        "快手",
        "哔哩哔哩",
        "滴滴",
        "携程",
        "小红书",
        "华为",
    ]

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.session_id: str | None = None
        self.question_id: str | None = None
        self.runner = TaskRunner(api, self)
        self.runner.failed.connect(self._failed)
        self.runner.idle.connect(self._ready)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("PageSurface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("模拟面试")
        title.setObjectName("PageTitle")
        subtitle = QLabel("选择目标岗位，Agent 将一次提出一个问题并根据回答追问")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        settings_panel = QFrame()
        settings_panel.setObjectName("InterviewSettings")
        settings = QHBoxLayout(settings_panel)
        settings.setContentsMargins(14, 12, 14, 12)
        settings.setSpacing(10)
        self.company_combo = QComboBox()
        self.company_combo.addItems(self.TARGET_COMPANIES)
        self.company_combo.setFixedWidth(210)
        self.position_input = QLineEdit("AI全栈开发工程师")
        self.position_input.setFixedWidth(240)
        self.round_combo = QComboBox()
        self.round_combo.addItems(["一面", "二面", "技术终面", "HR 面"])
        self.round_combo.setFixedWidth(130)
        start_button = self.start_button = QPushButton("开始面试")
        start_button.setObjectName("PrimaryButton")
        start_button.clicked.connect(self._start_interview)
        settings.addWidget(self.company_combo)
        settings.addWidget(self.position_input)
        settings.addWidget(self.round_combo)
        settings.addWidget(start_button)
        self.restore_button = QPushButton("恢复上次")
        self.restore_button.setObjectName("SecondaryButton")
        self.restore_button.clicked.connect(self._restore)
        settings.addWidget(self.restore_button)
        settings.addStretch()
        layout.addWidget(settings_panel)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setObjectName("MutedLabel")
        layout.addWidget(self.notice)

        self.transcript = QTextBrowser()
        self.transcript.setObjectName("InterviewTranscript")
        self.transcript.setHtml("<p style='color:#817B91'>配置目标岗位后开始模拟面试。</p>")
        layout.addWidget(self.transcript, 1)

        self.answer_input = QPlainTextEdit()
        self.answer_input.setObjectName("InterviewAnswer")
        self.answer_input.setPlaceholderText("输入你的回答")
        self.answer_input.setFixedHeight(110)
        layout.addWidget(self.answer_input)

        actions = QHBoxLayout()
        finish_button = self.finish_button = QPushButton("结束并生成总结")
        finish_button.setObjectName("SecondaryButton")
        finish_button.clicked.connect(self._finish_interview)
        submit_button = self.submit_button = QPushButton("提交回答")
        submit_button.setObjectName("PrimaryButton")
        submit_button.clicked.connect(self._submit_answer)
        actions.addStretch()
        actions.addWidget(finish_button)
        actions.addWidget(submit_button)
        layout.addLayout(actions)

    def _start_interview(self) -> None:
        if self.runner.busy:
            return
        position_name = self.position_input.text().strip()
        if not position_name:
            self.notice.setText("请先填写目标岗位。")
            return
        self._busy("正在生成面试题…")
        self.runner.start("create_mock_interview", self._started,
            company_name=(
                None if self.company_combo.currentIndex() == 0 else self.company_combo.currentText()
            ),
            position_name=position_name,
            interview_round=self.round_combo.currentText(),
            interview_focus=["AI应用", "全栈开发", "Agent"],
        )

    def _started(self, result):
        self.session_id = result["session_id"]
        self.question_id = result["question_id"]
        self.transcript.clear()
        self._append_interviewer(result["question"])
        QSettings("InterviewAssistant", "Client").setValue("last_mock_session", self.session_id)
        self.notice.setText("模拟面试已开始。")

    def _submit_answer(self) -> None:
        if self.runner.busy:
            return
        answer = self.answer_input.toPlainText().strip()
        if not self.session_id or not self.question_id:
            self.notice.setText("请先开始模拟面试。")
            return
        if not answer:
            return
        self._pending_answer = answer
        self._busy("正在评价回答…")
        self.runner.start("submit_mock_answer", self._answered,
            session_id=self.session_id, question_id=self.question_id, answer=answer)

    def _answered(self, result):
        self.answer_input.clear()
        self.transcript.append(f"<p><b>我：</b>{escape(self._pending_answer)}</p>")
        self.transcript.append(
            f"<p style='color:#6D3CF0'><b>评价：</b>{escape(result['evaluation'])}（{result['score']} 分）</p>"
        )
        self.question_id = result["question_id"]
        if result["question"]:
            self._append_interviewer(result["question"])
        else:
            self.notice.setText("题目已完成，可以生成面试总结。")

    def _finish_interview(self) -> None:
        if self.runner.busy:
            return
        if not self.session_id:
            self.notice.setText("当前没有进行中的模拟面试。")
            return
        self._busy("正在生成总结…")
        self.runner.start("finish_mock_interview", self._finished_interview, session_id=self.session_id)

    def _finished_interview(self, result):
        self.transcript.append(
            "<hr>"
            f"<p><b>面试总结（{result['overall_score']} 分）</b></p>"
            f"<p>{escape(result['summary'])}</p>"
            f"<p><b>改进建议：</b>{escape('；'.join(result['suggestions']))}</p>"
        )
        self.notice.setText("模拟面试总结已保存。")
        self.session_id = None
        self.question_id = None

    def _restore(self):
        """通过服务端恢复上次保存的会话，不依赖本地对话文本。"""
        if self.runner.busy:
            return
        session_id = QSettings("InterviewAssistant", "Client").value("last_mock_session")
        if not session_id or not hasattr(self.api, "get_mock_interview"):
            self.notice.setText("没有可恢复的面试会话。")
            return
        self._busy("正在恢复…")
        self.runner.start("get_mock_interview", self._restored, session_id=session_id)

    def _restored(self, result):
        self.session_id = result["session_id"]
        context = result.get("context", {})
        self.company_combo.setCurrentText(context.get("company_name") or self.TARGET_COMPANIES[0])
        self.position_input.setText(context.get("position_name", "AI全栈开发工程师"))
        self.round_combo.setCurrentText(context.get("interview_round", "一面"))
        self.transcript.clear()
        for turn in result["turns"]:
            self._append_interviewer(turn["question"])
            if "answer" in turn:
                self.transcript.append(f"<p><b>我：</b>{escape(turn['answer'])}</p>")
                evaluation = turn.get("result", {})
                self.transcript.append(f"<p style='color:#6D3CF0'><b>评价：</b>{escape(evaluation.get('evaluation', ''))}（{evaluation.get('score', 0)} 分）</p>")
        self.question_id = result["turns"][-1]["question_id"] if result["status"] == "in_progress" else None
        self.notice.setText("已恢复上次面试。")
        if result.get("report"):
            self._finished_interview(result["report"])

    def _busy(self, message):
        self.notice.setText(message)
        for button in (self.start_button, self.restore_button, self.submit_button, self.finish_button):
            button.setEnabled(False)

    def _ready(self):
        for button in (self.start_button, self.restore_button, self.submit_button, self.finish_button):
            button.setEnabled(True)

    def _failed(self, message):
        self.notice.setText(message)

    def _append_interviewer(self, question: str) -> None:
        self.transcript.append(
            f"<p style='color:#302A42'><b>面试官：</b>{escape(question)}</p>"
        )
