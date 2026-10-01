"""使用用户已登录的专用浏览器配置读取可见的 BOSS 岗位页面。"""

from threading import Lock
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Error as BrowserError

from backend.app.core.config import get_settings
from backend.app.core.exceptions import ApplicationError

_BROWSER_LOCK = Lock()


def valid_job_url(url: str) -> bool:
    """仅接受 BOSS 岗位详情页链接，不访问模型生成的其他域名。"""
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == "www.zhipin.com" and parsed.path.startswith("/job_detail/") and parsed.path.endswith(".html")


class BossJobSource:
    """仅使用页面可见文本；登录和验证由用户完成。"""

    def __init__(self, settings=None):
        """使用配置的专用浏览器资料目录和已安装的浏览器通道。"""
        self.settings = settings or get_settings()

    async def search(self, keywords: list[str], limit: int) -> list[dict]:
        """返回实际读取的 JD 文本及原始链接，或明确的登录、验证错误。"""
        if not (self.settings.boss_profile_path / ".configured").exists():
            raise ApplicationError("BOSS_LOGIN_REQUIRED", "请先运行 start-boss-login.bat，在专用浏览器中登录 BOSS 后重试。", status_code=503)
        if not _BROWSER_LOCK.acquire(blocking=False):
            raise ApplicationError("BOSS_BUSY", "已有岗位搜索正在运行，请稍后再试。", status_code=409)
        try:
            try:
                async with async_playwright() as playwright:
                    context = await playwright.chromium.launch_persistent_context(
                        str(self.settings.boss_profile_path), channel=self.settings.boss_browser_channel,
                        headless=True, viewport={"width": 1440, "height": 960},
                    )
                    try:
                        page = await context.new_page()
                        page.set_default_timeout(15000)
                        query = " ".join(keywords) or "Java 校招"
                        await page.goto("https://www.zhipin.com/web/geek/job?query=" + quote(query), wait_until="domcontentloaded")
                        try:
                            await page.locator('a[href*="/job_detail/"]').first.wait_for(timeout=15000)
                        except BrowserError as exc:
                            raise ApplicationError("BOSS_LOGIN_OR_VERIFICATION", "BOSS 未显示岗位，可能需要登录、验证或暂无结果，请在专用浏览器检查。", status_code=503) from exc
                        hrefs = await page.locator('a[href*="/job_detail/"]').evaluate_all("nodes => nodes.map(n => n.href)")
                        urls = list(dict.fromkeys(url for url in hrefs if valid_job_url(url)))[:limit]
                        jobs = []
                        for url in urls:
                            await page.goto(url, wait_until="domcontentloaded")
                            try:
                                await page.locator("h1").first.wait_for(timeout=10000)
                            except BrowserError:
                                raise ApplicationError("BOSS_DETAIL_UNAVAILABLE", "岗位详情需要验证或页面结构发生变化，未生成推荐。", status_code=503)
                            if not valid_job_url(page.url):
                                raise ApplicationError("BOSS_LOGIN_OR_VERIFICATION", "岗位详情跳转到登录或验证页面，请先处理。", status_code=503)
                            soup = BeautifulSoup(await page.content(), "html.parser")
                            for tag in soup(["script", "style", "nav", "footer"]):
                                tag.decompose()
                            text = soup.get_text("\n", strip=True)
                            if not any(word in text for word in ("职位描述", "岗位职责", "任职要求")):
                                raise ApplicationError("BOSS_JD_MISSING", "页面没有可确认的 JD，未生成推荐。", status_code=502)
                            jobs.append({"job_url": url, "job_description": text[:30000]})
                        return jobs
                    finally:
                        await context.close()
            except BrowserError as exc:
                raise ApplicationError("BOSS_BROWSER_FAILED", "BOSS 浏览器启动或读取失败；请关闭登录窗口并检查 BOSS_BROWSER_CHANNEL。", status_code=503) from exc
        finally:
            _BROWSER_LOCK.release()
