"""用普通浏览器进程保存 BOSS 登录与人工验证状态。"""

from __future__ import annotations

import subprocess

from backend.app.core.config import get_settings
from backend.app.integrations.boss import browser_executable


def main() -> None:
    """打开独立资料目录，由用户完成登录和验证后保存配置标记。"""
    settings = get_settings()
    settings.boss_profile_path.mkdir(parents=True, exist_ok=True)
    executable = browser_executable(settings.boss_browser_channel)
    url = (
        "https://www.zhipin.com/c101210100/"
        "?query=Java&industry=&position=&page=1"
    )
    process = subprocess.Popen([
        str(executable),
        f"--user-data-dir={settings.boss_profile_path.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "--start-maximized",
        url,
    ])
    print("已使用普通浏览器打开 BOSS 专用资料目录。")
    print("请完成登录或安全验证，并确认页面能显示岗位列表。")
    input("确认后先关闭这个专用浏览器窗口，再按回车保存状态：")
    if process.poll() is None:
        print("浏览器仍在运行；请关闭专用窗口后再等待程序继续。")
        process.wait()
    (settings.boss_profile_path / ".configured").touch()
    print("专用登录与验证状态已保存，可以运行岗位采集。")


if __name__ == "__main__":
    main()
