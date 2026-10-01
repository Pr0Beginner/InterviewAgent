"""测试流式请求、页面切换及窗口关闭时的 Qt 生命周期。"""

import asyncio
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QDateTime, QPoint, QPointF, QTime, Qt
from PySide6.QtGui import QTextCursor, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCalendarWidget, QFrame, QPushButton

from client.api.mock_api import MockApiClient
from client.ui.main_window import MainWindow
from client.ui.pages.dashboard_page import DashboardPage, SummaryCard
from client.ui.widgets.agent_panel import AgentPanel, _agent_bubble
from client.ui.widgets.datetime_picker import DateTimePicker, DateTimePickerDialog
from client.ui.widgets.dialogs import AppDialog


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

    def test_suggestions_preserve_draft_without_sending(self):
        api = DelayedApi()
        panel = AgentPanel(api)
        panel.input.setPlainText("先了解上海的岗位")
        panel.set_page_context("recommendations")
        button = panel.suggestion_buttons[0]
        button.click()
        self.assertEqual(panel.input.toPlainText(), "先了解上海的岗位\n" + button.text())
        self.assertIsNone(api.captured)
        self.assertFalse(panel.is_busy)
        panel.close()

    def test_summary_can_be_filtered_from_keyboard(self):
        page = DashboardPage(MockApiClient())
        page.show()
        card = next(card for card in page.findChildren(SummaryCard) if card.filter_value == "待面试")
        card.setFocus()
        QTest.keyClick(card, Qt.Key.Key_Return)
        self.assertEqual(page.filter_combo.currentText(), "待面试")
        self.assertGreater(page.table.rowCount(), 0)
        for row in range(page.table.rowCount()):
            self.assertEqual(page.table.cellWidget(row, page.STATUS_COLUMN).currentText(), "待面试")
        page.close()

    def test_empty_records_and_operation_feedback_remain_visible(self):
        api = MockApiClient()
        api._interviews.clear()
        page = DashboardPage(api)
        page.show()
        self.assertEqual(page.table_stack.currentIndex(), 1)
        self.assertTrue(page.integration_notice.isHidden())
        page.integration_notice.setText("连接失败，请重试。")
        self.assertFalse(page.integration_notice.isHidden())
        page.integration_notice.setText("")
        self.assertTrue(page.integration_notice.isHidden())
        page.close()

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
        self.assertIsInstance(page.table.cellWidget(0, page.START_TIME_COLUMN), DateTimePicker)
        self.assertIsInstance(page.table.cellWidget(0, page.END_TIME_COLUMN), DateTimePicker)
        self.assertEqual(page.filter_combo.maxVisibleItems(), 6)
        self.assertEqual(page.table.cellWidget(0, page.STATUS_COLUMN).maxVisibleItems(), 6)
        page.close()

    def test_datetime_wheel_does_not_change_value(self):
        """鼠标滚轮不能意外改变开始时间或结束时间。"""
        editor = DateTimePicker("2026-10-08 14:00", "选择开始时间")
        before = editor.value()
        event = QWheelEvent(
            QPointF(8, 8), QPointF(8, 8), QPoint(), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate, False,
        )
        QApplication.sendEvent(editor, event)
        self.assertEqual(editor.value(), before)

    def test_datetime_picker_has_calendar_hour_and_minute_controls(self):
        """时间选择弹窗必须同时提供日期、小时和分钟控件。"""
        page = DashboardPage(MockApiClient())
        dialog = DateTimePickerDialog(
            page,
            title="选择开始时间",
            value=QDateTime(QDate(2026, 10, 8), QTime(14, 30)),
        )
        self.assertIsNotNone(dialog.findChild(QCalendarWidget, "DateTimeCalendar"))
        self.assertEqual(dialog.hour_combo.count(), 24)
        self.assertEqual(dialog.minute_combo.count(), 60)

        dialog.hour_combo.setCurrentIndex(14)
        wheel_event = QWheelEvent(
            QPointF(8, 8), QPointF(8, 8), QPoint(), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate, False,
        )
        QApplication.sendEvent(dialog.hour_combo, wheel_event)
        self.assertEqual(dialog.hour_combo.currentIndex(), 14)

        dialog.calendar.setSelectedDate(QDate(2026, 10, 12))
        dialog.hour_combo.setCurrentIndex(9)
        dialog.minute_combo.setCurrentIndex(45)
        dialog._accept_value()
        self.assertEqual(dialog.result_value.toString("yyyy-MM-dd HH:mm"), "2026-10-12 09:45")
        dialog.close()
        page.close()

    def test_discard_button_tracks_dirty_rows(self):
        """放弃修改按钮只在表格存在未保存内容时可用。"""
        page = DashboardPage(MockApiClient())
        self.assertFalse(page.discard_button.isEnabled())
        original = page.table.item(0, page.COMPANY_COLUMN).text()
        page.table.item(0, page.COMPANY_COLUMN).setText(original + "测试")
        self.assertTrue(page.discard_button.isEnabled())
        page.discard_changes()
        self.assertFalse(page.discard_button.isEnabled())
        self.assertEqual(page.table.item(0, page.COMPANY_COLUMN).text(), original)
        page.close()

    def test_custom_dialog_uses_application_components(self):
        """确认弹窗使用应用自己的表面和按钮，不依赖系统消息框。"""
        page = DashboardPage(MockApiClient())
        dialog = AppDialog(
            page, title="有尚未保存的修改", message="是否保存？",
            primary_text="保留修改", destructive_text="放弃修改",
        )
        self.assertIsNotNone(dialog.findChild(QFrame, "DialogSurface"))
        self.assertIsNotNone(dialog.findChild(QPushButton, "PrimaryButton"))
        self.assertIsNotNone(dialog.findChild(QPushButton, "DangerButton"))
        dialog.close()
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
