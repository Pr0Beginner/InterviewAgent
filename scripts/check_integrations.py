"""只读验证网易邮箱，并可选检查 BOSS 页面；不调用付费模型。"""

import argparse
import asyncio
import json
import tempfile

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Error as BrowserError

from backend.app.core.config import get_settings
from backend.app.core.exceptions import ApplicationError
from backend.app.integrations.mail import NeteaseMailbox


def check_mail():
    """使用 IMAP 只读收件箱和 PEEK，核对读取前后未读集合一致。"""
    mailbox = NeteaseMailbox()
    with mailbox.connect(readonly=True) as client:
        before = mailbox.unread(client, 5)
        fetched = bool(mailbox.fetch(client, before[-1]["uid"])) if before else False
        after = mailbox.unread(client, 5)
    return {"status": "success", "sampled_unread": len(before), "peek_fetched": fetched,
            "sample_unchanged": before == after, "readonly": True}


async def check_boss():
    """验证公开 HTML 和一次浏览器渲染，不读取用户 Cookie、不重试验证页面。"""
    settings = get_settings()
    url = "https://www.zhipin.com/web/geek/job?query=Java"
    result = {"saved_login": (settings.boss_profile_path / ".configured").exists()}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(url)
            soup = BeautifulSoup(response.text, "html.parser")
            result.update(http_status=response.status_code, static_job_links=len(soup.select('a[href*="/job_detail/"]')))
    except httpx.HTTPError as exc:
        result["http_error"] = type(exc).__name__
    with tempfile.TemporaryDirectory(prefix="ia-boss-probe-") as directory:
        try:
            async with async_playwright() as playwright:
                context = await playwright.chromium.launch_persistent_context(directory, channel=settings.boss_browser_channel, headless=True)
                try:
                    page = context.pages[0] if context.pages else await context.new_page()
                    navigations = []
                    page.on("framenavigated", lambda frame: navigations.append(frame.url) if frame == page.main_frame else None)
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_timeout(4000)
                    result.update(browser_title=await page.title(), browser_url=page.url.split("?")[0],
                                  browser_job_links=await page.locator('a[href*="/job_detail/"]').count(), main_navigations=len(navigations))
                    visible = await page.locator("body").inner_text(timeout=5000)
                    result["verification_visible"] = any(word in visible for word in ("安全验证", "访问异常", "滑块验证", "请完成验证"))
                finally:
                    await context.close()
        except BrowserError as exc:
            result["browser_error"] = type(exc).__name__
    return result


def main():
    """默认检查邮箱；--boss 额外进行一次不登录的公开页面探测。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boss", action="store_true", help="额外只读验证 BOSS 公开页面")
    args = parser.parse_args()
    try:
        result = check_mail()
    except ApplicationError as exc:
        result = {"status": "failed", "code": exc.code, "message": exc.message}
    print(json.dumps({"check": "netease", **result}, ensure_ascii=False), flush=True)
    if args.boss:
        print(json.dumps({"check": "boss", **asyncio.run(check_boss())}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
