"""测试流式请求、页面切换及窗口关闭时的 Qt 生命周期。"""

import asyncio
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from client.api.mock_api import MockApiClient
from client.ui.main_window import MainWindow
from client.ui.pages.dashboard_page import DashboardPage, OptionalDateTimeEdit
from client.ui.widgets.agent_panel import AgentPanel, _agent_bubble


class DelayedApi(MockApiClient):
    def __init__(self, delay=0.08):
        super().__init__()
        self.delay = delay
        self.captured = None

    async def stream_chat_completion(self, messages, model="interview-assistant", metadata=None, extensions=None):
        self.captured = {"messages": messages, "metadata": metadata}
        await asyncio.sleep(self.delay)
        async for chunk in super().stream_chat_completion(messages, model, metadata, extensions):
            yield chunk


class AgentPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate())

    def test_tab_switch_keeps_reply_in_originating_conversation(self):
        api = DelayedApi()
        panel = AgentPanel(api)
        panel.input.setPlainText("我目前有哪些面试？")
        panel._send_message()
        panel.set_page_context("recommendations")
        self.wait_until(lambda: not panel.is_busy)
        self.assertEqual(api.captured["metadata"]["page_context"], "applications")
        self.assertEqual(len(panel._histories["applications"]), 2)
        self.assertEqual(panel._histories["recommendations"], [])
        self.assertIn("进行中", panel.messages.toPlainText())
        panel.close()

    def test_cancel_discards_failed_exchange_and_restores_input(self):
        panel = AgentPanel(DelayedApi(30))
        panel.input.setPlainText("查面试")
        panel._send_message()
        panel.cancel()
        self.wait_until(lambda: not panel.is_busy)
        self.assertEqual(panel._histories["applications"], [])
        self.assertEqual(panel.input.toPlainText(), "查面试")
        panel.close()

    def test_enter_sends_and_shift_enter_adds_newline(self):
        """输入框回车发送，Shift+回车只插入换行。"""
        api = DelayedApi()
        panel = AgentPanel(api)
        panel.show()
        panel.input.setFocus()
        panel.input.setPlainText("第一行")
        panel.input.moveCursor(QTextCursor.MoveOperation.End)
        QTest.keyClick(panel.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(panel.input.toPlainText(), "第一行\n")
        self.assertFalse(panel.is_busy)
        panel.input.insertPlainText("第二行")
        QTest.keyClick(panel.input, Qt.Key.Key_Return)
        self.wait_until(lambda: api.captured is not None)
        self.assertEqual(api.captured["messages"][-1]["content"], "第一行\n第二行")
        self.wait_until(lambda: not panel.is_busy)
        panel.close()

    def test_agent_panel_width_can_be_changed_with_splitter(self):
        """主内容与 Agent 面板之间的分隔条能够改变右侧宽度。"""
        window = MainWindow(MockApiClient())
        window.show()
        self.app.processEvents()
        initial_width = window.agent_panel.width()
        window.content_splitter.setSizes([850, 560])
        self.app.processEvents()
        self.assertEqual(window.content_splitter.count(), 2)
        self.assertGreater(window.agent_panel.width(), initial_width)
        window.close()

    def test_mock_interview_page_hides_agent_panel(self):
        """模拟面试页面使用完整内容宽度，不显示右侧通用 Agent。"""
        window = MainWindow(MockApiClient())
        window.show()
        window._navigate_to(2, window.nav_buttons[2])
        self.app.processEvents()
        self.assertFalse(window.agent_panel.isVisible())
        self.assertEqual(window.mock_page.position_input.text(), "AI全栈开发工程师")
        window._navigate_to(0, window.nav_buttons[0])
        self.app.processEvents()
        self.assertTrue(window.agent_panel.isVisible())
        window.close()

    def test_dashboard_uses_scrollable_status_and_start_end_time_editors(self):
        """投递页按开始时间降序展示，并用时间选择器编辑起止时间。"""
        page = DashboardPage(MockApiClient())
        self.assertEqual(page.SUMMARY_CARDS[1], ("笔试中", "笔试中"))
        self.assertEqual(page.table.horizontalHeaderItem(page.START_TIME_COLUMN).text(), "开始时间")
        self.assertEqual(page.table.horizontalHeaderItem(page.END_TIME_COLUMN).text(), "结束时间")
        self.assertEqual(page.table.item(0, page.COMPANY_COLUMN).text(), "百度")
        self.assertIsInstance(page.table.cellWidget(0, page.START_TIME_COLUMN), OptionalDateTimeEdit)
        self.assertIsInstance(page.table.cellWidget(0, page.END_TIME_COLUMN), OptionalDateTimeEdit)
        self.assertEqual(page.filter_combo.maxVisibleItems(), 6)
        self.assertEqual(page.table.cellWidget(0, page.STATUS_COLUMN).maxVisibleItems(), 6)
        page.close()

    def test_agent_reply_renders_markdown_and_escapes_raw_html(self):
        """助手回复支持 Markdown，同时不执行模型返回的原始 HTML。"""
        html = _agent_bubble("**重点**\n\n- 第一项\n- 第二项\n\n<script>bad()</script>")
        self.assertIn("font-weight:700", html)
        self.assertIn("<ul", html)
        self.assertNotIn("<script>", html)

    def test_window_close_cancels_request_before_destroying_thread(self):
        window = MainWindow(DelayedApi(30))
        window.show()
        window.agent_panel.input.setPlainText("查面试")
        window.agent_panel._send_message()
        window.close()
        self.wait_until(lambda: not window.isVisible())
        self.assertFalse(window.agent_panel.is_busy)


if __name__ == "__main__":
    unittest.main()
