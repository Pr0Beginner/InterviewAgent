"""Windows 一键启动脚本的重启行为测试。"""

import unittest
from unittest.mock import Mock, patch

from scripts import start_app


class StartAppTest(unittest.TestCase):
    @patch("scripts.start_app.time.sleep")
    @patch("scripts.start_app.后端健康", return_value=False)
    @patch("scripts.start_app.subprocess.run")
    def test_stop_running_backend_targets_listener_pid(self, run, _healthy, _sleep):
        run.return_value = Mock(returncode=0, stdout="1234,5678\n", stderr="")

        stopped = start_app.停止已运行后端()

        self.assertEqual(stopped, [1234, 5678])
        command = run.call_args.args[0]
        self.assertEqual(command[0], "powershell.exe")
        self.assertIn("Get-NetTCPConnection -LocalPort 8000", command[-1])
        self.assertIn("Stop-Process -Id $processId", command[-1])

    @patch("scripts.start_app.结束进程")
    @patch("scripts.start_app.subprocess.run")
    @patch("scripts.start_app.启动后端")
    @patch("scripts.start_app.停止已运行后端", return_value=[1234])
    @patch("scripts.start_app.后端健康", return_value=True)
    def test_main_restarts_healthy_backend(
        self, _healthy, stop_existing, start_backend, run_client, finish_backend
    ):
        backend_process = Mock()
        start_backend.return_value = backend_process
        run_client.return_value = Mock(returncode=0)

        self.assertEqual(start_app.main(), 0)

        stop_existing.assert_called_once_with()
        start_backend.assert_called_once_with()
        finish_backend.assert_called_once_with(backend_process)


if __name__ == "__main__":
    unittest.main()
