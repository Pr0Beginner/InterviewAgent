"""推荐岗位页的多选城市、字段层级和 JD 悬浮行为测试。"""

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from client.api.mock_api import MockApiClient
from client.ui.pages.jobs_page import CityMultiSelect, HoverJobDescription, JobsPage


class CapturingApi(MockApiClient):
    def __init__(self):
        super().__init__()
        self.job_params = None

    def recommend_jobs(self, *args, **kwargs):
        self.job_params = kwargs
        return super().recommend_jobs(*args, **kwargs)


class JobsPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate())

    def test_city_picker_supports_multiple_values(self):
        picker = CityMultiSelect(["上海", "杭州"])
        self.assertEqual(picker.selected_cities(), ["上海", "杭州"])
        picker.options["北京"].setChecked(True)
        self.assertEqual(picker.selected_cities(), ["北京", "上海", "杭州"])
        self.assertIn("北京", picker.button.text())

    def test_jd_is_hidden_until_hover_or_focus(self):
        hover = HoverJobDescription("岗位职责：开发服务。")
        hover.show()
        self.app.processEvents()
        hover.clearFocus()
        QApplication.sendEvent(hover, QEvent(QEvent.Type.Leave))
        self.assertTrue(hover.preview.isHidden())
        QApplication.sendEvent(hover, QEvent(QEvent.Type.Enter))
        self.assertFalse(hover.preview.isHidden())
        QApplication.sendEvent(hover, QEvent(QEvent.Type.Leave))
        self.assertTrue(hover.preview.isHidden())

    def test_page_defaults_to_graduate_experience_and_renders_right_actions(self):
        api = CapturingApi()
        page = JobsPage(api)
        page.show()
        self.wait_until(lambda: not page.runner.busy)
        self.assertFalse(hasattr(page, "tech_input"))
        self.assertNotIn("tech_stack", api.job_params)
        self.assertEqual(page.experience_combo.currentText(), "应届生")
        self.assertEqual(api.job_params["work_experience"], "应届生")
        object_names = {label.objectName() for label in page.findChildren(QLabel)}
        self.assertIn("JobSequence", object_names)
        self.assertIn("JobSalary", object_names)
        self.assertIn("JobLink", object_names)
        self.assertIn("JdTrigger", object_names)
        actions = page.findChildren(QFrame, "JobActions")
        self.assertTrue(actions)
        self.assertTrue(all(
            action.findChild(QLabel, "JobLink") is not None
            and action.findChild(HoverJobDescription) is not None
            for action in actions
        ))
        self.assertTrue(all(hover.preview.isHidden() for hover in page.findChildren(HoverJobDescription)))
        page.close()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
