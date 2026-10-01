"""由用户主动发起，在独立浏览器配置中交互式登录 BOSS。"""

import asyncio

from playwright.async_api import async_playwright

from backend.app.core.config import get_settings


async def main():
    """保持可见的登录浏览器打开，直到用户确认操作完成。"""
    settings = get_settings()
    settings.boss_profile_path.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(settings.boss_profile_path), channel=settings.boss_browser_channel, headless=False,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            # 仅打开一次首页；后续跳转由用户操作，不自动刷新或循环进入岗位页。
            await page.goto("https://www.zhipin.com/", wait_until="domcontentloaded")
            print("如果网页反复刷新，请先关闭浏览器；程序不会自动刷新，可能是网页验证或浏览器兼容问题。")
            await asyncio.to_thread(input, "请在浏览器中登录并完成必要验证，看到岗位列表后按回车关闭：")
            links = sum([await item.locator('a[href*="/job_detail/"]').count() for item in context.pages if "www.zhipin.com" in item.url])
            if not links:
                print("未检测到岗位列表，登录标记未保存。请重试。")
                return
            (settings.boss_profile_path / ".configured").touch()
            print("专用登录状态已保存，可以回到推荐岗位页点击重新匹配。")
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
