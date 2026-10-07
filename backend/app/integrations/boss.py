"""低频读取用户浏览器中可见的 BOSS 岗位列表和详情。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
from pathlib import Path
import re
import shutil
import socket
import subprocess
from threading import Lock
from time import perf_counter
from urllib.parse import urlencode, urljoin, urlparse
import urllib.request

from bs4 import BeautifulSoup
from playwright.async_api import (
    Error as BrowserError,
    TimeoutError as BrowserTimeoutError,
    async_playwright,
)

from backend.app.core.config import get_settings
from backend.app.core.exceptions import ApplicationError

LOGGER = logging.getLogger(__name__)
_BROWSER_LOCK = Lock()
_SEARCH_URL = "https://www.zhipin.com"
_DETAIL_MARKERS = ("职位描述", "岗位职责", "主要职责", "工作内容", "任职要求", "职位要求")
_NO_RESULT_MARKERS = ("暂无相关职位", "没有找到相关职位", "暂无符合条件的职位")
_VERIFY_MARKERS = ("安全验证", "请完成验证", "访问过于频繁", "异常访问", "拖动滑块")
_LOGIN_MARKERS = ("登录后查看", "请先登录", "登录 BOSS 直聘", "登录BOSS直聘")
_EXPERIENCE_MARKERS = {
    "应届生": ("在校/应届", "应届", "校招", "毕业生", "经验不限", "1年以内"),
    "1年以内": ("1年以内",),
    "1-3年": ("1-3年",),
    "3-5年": ("3-5年",),
    "5-10年": ("5-10年",),
    "10年以上": ("10年以上",),
}

# 仅为常见城市维护显式映射；未知城市降级为关键词的一部分，不猜测代码。
CITY_CODES = {
    "北京": "101010100",
    "上海": "101020100",
    "天津": "101030100",
    "重庆": "101040100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "南京": "101190100",
    "苏州": "101190400",
    "武汉": "101200100",
    "成都": "101270100",
    "西安": "101110100",
    "长沙": "101250100",
}


@dataclass(frozen=True, slots=True)
class BossSearchPlan:
    """一次可审计的列表页请求。"""

    keyword: str
    city: str
    page: int
    work_experience: str = "应届生"


def valid_job_url(url: str) -> bool:
    """仅接受 HTTPS 的 BOSS 岗位详情页，不访问页面注入的其他域名。"""
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "www.zhipin.com"
        and port in {None, 443}
        and re.fullmatch(r"/job_detail/[^/]+\.html", parsed.path) is not None
    )


def canonical_job_url(url: str) -> str:
    """移除岗位链接中的追踪参数；不合规链接返回空字符串。"""
    absolute = urljoin("https://www.zhipin.com/", url.strip())
    if not valid_job_url(absolute):
        return ""
    parsed = urlparse(absolute)
    return parsed._replace(query="", fragment="").geturl()


def build_search_plans(
    keywords: list[str],
    cities: list[str] | None,
    pages_per_query: int,
    max_plans: int,
    work_experience: str = "应届生",
) -> list[BossSearchPlan]:
    """按城市、关键词、页码生成有限搜索计划并去除重复输入。"""
    clean_keywords = _unique_text(keywords) or ["Java 校招"]
    clean_cities = _unique_text(cities or []) or [""]
    plans: list[BossSearchPlan] = []
    for city in clean_cities:
        for keyword in clean_keywords:
            for page in range(1, pages_per_query + 1):
                plans.append(BossSearchPlan(
                    keyword=keyword,
                    city=city,
                    page=page,
                    work_experience=work_experience,
                ))
                if len(plans) >= max_plans:
                    return plans
    return plans


def build_search_url(plan: BossSearchPlan) -> str:
    """使用 BOSS 当前城市页提供的查询路由，未知城市并入关键词。"""
    search_terms = [plan.keyword]
    if plan.work_experience != "不限":
        search_terms.append(plan.work_experience)
    parameters = {
        "query": " ".join(search_terms),
        "industry": "",
        "position": "",
        "page": str(plan.page),
    }
    city_code = CITY_CODES.get(plan.city)
    if plan.city and not city_code:
        parameters["query"] += f" {plan.city}"
    city_code = city_code or "100010000"
    return f"{_SEARCH_URL}/c{city_code}/?" + urlencode(parameters)


def extract_job_description(html: str) -> str:
    """优先提取 JD 区块，选择器变化时降级为去噪后的页面可见文本。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript", "svg"]):
        tag.decompose()

    candidates: list[str] = []
    for selector in (
        ".job-sec-text",
        ".job-detail-section",
        ".job-detail-content",
        "[class*='job-detail']",
    ):
        for node in soup.select(selector):
            text = _normalize_space(node.get_text("\n", strip=True))
            if text and text not in candidates:
                candidates.append(text)
        if any(any(marker in text for marker in _DETAIL_MARKERS) for text in candidates):
            break

    full_text = _normalize_space(soup.get_text("\n", strip=True))
    marked = [text for text in candidates if any(marker in text for marker in _DETAIL_MARKERS)]
    if marked:
        return _normalize_description(max(marked, key=len))[:30000]
    if any(marker in full_text for marker in _DETAIL_MARKERS):
        return _normalize_description(full_text)[:30000]
    return ""


def normalize_listing(raw: dict, plan: BossSearchPlan) -> dict | None:
    """清洗浏览器返回的列表卡片，并生成详情抓取所需的稳定字段。"""
    url = canonical_job_url(str(raw.get("href") or ""))
    if not url:
        return None
    path_name = urlparse(url).path.rsplit("/", 1)[-1]
    summary = _clean_summary(raw.get("summary"))[:4000]
    location = _clean_value(raw.get("location"))
    if not location and plan.city:
        match = re.search(rf"{re.escape(plan.city)}(?:·[\w\u4e00-\u9fff]+){{1,2}}", summary)
        location = match.group(0) if match else plan.city
    return {
        "job_url": url,
        "job_id": path_name.removesuffix(".html"),
        "position_name": _clean_value(raw.get("title")),
        "company_name": _clean_value(raw.get("company")),
        "salary": _clean_salary(raw.get("salary")),
        "base_location": location or plan.city,
        "list_summary": summary,
        "search_keyword": plan.keyword,
        "search_city": plan.city,
        "search_work_experience": plan.work_experience,
    }


def matches_work_experience(listing: dict, work_experience: str) -> bool:
    """根据列表页明确展示的经验标签过滤，避免把资深岗位交给应届生。"""
    if work_experience == "不限":
        return True
    markers = _EXPERIENCE_MARKERS.get(work_experience, (work_experience,))
    text = " ".join((listing.get("position_name") or "", listing.get("list_summary") or ""))
    return any(marker in text for marker in markers)


def browser_executable(channel: str) -> Path:
    """解析项目支持的本机浏览器，不下载或安装额外软件。"""
    names = {
        "msedge": ("msedge.exe", "msedge"),
        "chrome": ("chrome.exe", "chrome"),
    }.get(channel, (channel,))
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved)
    candidates = {
        "msedge": (
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ),
        "chrome": (
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ),
    }.get(channel, ())
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ApplicationError(
        "BOSS_BROWSER_MISSING",
        f"找不到浏览器通道 {channel}，请检查 BOSS_BROWSER_CHANNEL。",
        status_code=503,
    )


class BossJobSource:
    """使用专用登录资料，按严格上限读取用户可见岗位，不绕过登录或验证。"""

    def __init__(self, settings=None, sleeper=None):
        self.settings = settings or get_settings()
        self._sleep = sleeper or asyncio.sleep

    async def search(
        self,
        keywords: list[str],
        limit: int,
        cities: list[str] | None = None,
        work_experience: str = "应届生",
    ) -> list[dict]:
        """搜索有限列表页，去重后低频读取详情并返回真实 JD。"""
        if not (self.settings.boss_profile_path / ".configured").exists():
            raise ApplicationError(
                "BOSS_LOGIN_REQUIRED",
                "请先运行 start-boss-login.bat，在专用浏览器中登录 BOSS 后重试。",
                status_code=503,
            )
        if not _BROWSER_LOCK.acquire(blocking=False):
            raise ApplicationError("BOSS_BUSY", "已有岗位搜索正在运行，请稍后再试。", status_code=409)

        plans = build_search_plans(
            keywords,
            cities,
            self.settings.jobs_pages_per_query,
            self.settings.jobs_max_search_pages,
            work_experience,
        )
        started_at = perf_counter()
        try:
            try:
                async with async_playwright() as playwright:
                    async with self._browser_page(playwright) as page:
                        listing_started_at = perf_counter()
                        listings = await self._collect_listings(page, plans, limit)
                        listing_elapsed = perf_counter() - listing_started_at
                        detail_started_at = perf_counter()
                        jobs = await self._collect_details(page, listings, limit)
                        LOGGER.info(
                            "boss_search_complete plans=%s listings=%s jobs=%s listing_ms=%d detail_ms=%d total_ms=%d",
                            len(plans),
                            len(listings),
                            len(jobs),
                            round(listing_elapsed * 1000),
                            round((perf_counter() - detail_started_at) * 1000),
                            round((perf_counter() - started_at) * 1000),
                        )
                        return jobs
            except BrowserError as exc:
                raise ApplicationError(
                    "BOSS_BROWSER_FAILED",
                    "BOSS 浏览器页面快照失败；请关闭其他专用登录窗口后重试。",
                    status_code=503,
                ) from exc
        finally:
            _BROWSER_LOCK.release()

    async def _collect_listings(self, page, plans: list[BossSearchPlan], limit: int) -> list[dict]:
        """执行有限搜索计划，并以岗位 URL 去重列表卡片。"""
        found: dict[str, dict] = {}
        exhausted_queries: set[tuple[str, str]] = set()
        requested = False
        for plan in plans:
            if len(found) >= limit:
                break
            query_key = (plan.city, plan.keyword)
            if query_key in exhausted_queries:
                continue
            if requested:
                await self._sleep(self.settings.jobs_request_interval_seconds)
            requested = True
            snapshot = await self._snapshot_with_retry(page, build_search_url(plan))
            rows = snapshot["rows"]
            if not rows:
                body = snapshot["body"]
                self._raise_for_access_page(snapshot["url"], body)
                if any(marker in body for marker in _NO_RESULT_MARKERS):
                    continue
                LOGGER.warning(
                    "boss_listing_empty url=%s title=%s",
                    snapshot["url"],
                    snapshot["title"],
                )
                continue
            new_on_page = 0
            for raw in rows:
                listing = normalize_listing(raw, plan)
                if (
                    listing
                    and matches_work_experience(listing, plan.work_experience)
                    and listing["job_id"] not in found
                ):
                    found[listing["job_id"]] = listing
                    new_on_page += 1
                    if len(found) >= limit:
                        break
            if plan.page > 1 and new_on_page == 0:
                exhausted_queries.add(query_key)

        if not found:
            raise ApplicationError(
                "BOSS_NO_JOBS",
                "BOSS 没有返回可读取的岗位。请检查关键词、城市或在登录浏览器中确认页面状态。",
                status_code=404,
            )
        return list(found.values())

    async def _collect_details(self, page, listings: list[dict], limit: int) -> list[dict]:
        """逐个读取详情；单个结构异常不会丢弃其他已成功岗位。"""
        jobs: list[dict] = []
        failures = 0
        for listing in listings[:limit]:
            await self._sleep(self.settings.jobs_request_interval_seconds)
            try:
                snapshot = await self._snapshot_with_retry(
                    page,
                    listing["job_url"],
                    include_html=True,
                )
            except BrowserError:
                failures += 1
                LOGGER.warning("boss_detail_unavailable job_id=%s", listing["job_id"])
                continue
            body = snapshot["body"]
            self._raise_for_access_page(snapshot["url"], body)
            current_url = canonical_job_url(snapshot["url"])
            if not current_url:
                raise ApplicationError(
                    "BOSS_LOGIN_OR_VERIFICATION",
                    "岗位详情跳转到登录或验证页面，请先在专用浏览器中处理。",
                    status_code=503,
                )
            description = extract_job_description(snapshot["html"])
            if not description:
                failures += 1
                LOGGER.warning("boss_jd_missing job_id=%s", listing["job_id"])
                continue
            resolved = {**listing}
            detail = snapshot.get("detail") or {}
            for key in ("position_name", "company_name", "salary"):
                value = _clean_salary(detail.get(key)) if key == "salary" else _clean_value(detail.get(key))
                if value:
                    resolved[key] = value
            # 列表页通常包含商圈，详情页只有城市；仅在列表缺失时使用详情地点。
            if not resolved.get("base_location"):
                resolved["base_location"] = _clean_value(detail.get("base_location"))
            jobs.append({
                **resolved,
                "job_url": current_url,
                "job_description": self._source_text(resolved, description),
            })

        if not jobs:
            raise ApplicationError(
                "BOSS_DETAIL_UNAVAILABLE",
                "已找到岗位列表，但详情页均无法确认有效 JD；页面结构可能已变化。",
                status_code=503,
                details={"listing_count": len(listings), "failed_details": failures},
            )
        return jobs

    async def _snapshot_with_retry(
        self,
        page,
        url: str,
        include_html: bool = False,
    ) -> dict:
        """Chrome 偶发在 CDP 接入瞬间关闭页面；只对该瞬时错误重试一次。"""
        for attempt in range(2):
            try:
                return await self._snapshot_page(page, url, include_html)
            except BrowserError:
                if attempt:
                    raise
                LOGGER.info("boss_snapshot_retry url=%s", url)
                await self._sleep(1)
        raise AssertionError("unreachable")

    @asynccontextmanager
    async def _browser_page(self, playwright):
        """一次搜索仅启动一个登录浏览器，并在全部列表和详情页之间复用。"""
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
        process = subprocess.Popen([
            str(browser_executable(self.settings.boss_browser_channel)),
            f"--user-data-dir={self.settings.boss_profile_path.resolve()}",
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            "about:blank",
        ])
        endpoint = f"http://127.0.0.1:{port}"
        browser = None
        try:
            await self._wait_for_debug_endpoint(endpoint, process)
            browser = await playwright.chromium.connect_over_cdp(endpoint)
            contexts = browser.contexts
            if not contexts:
                raise ApplicationError(
                    "BOSS_PAGE_MISSING",
                    "Chrome 已启动，但没有可用浏览器上下文。",
                    status_code=503,
                )
            pages = contexts[0].pages
            page = pages[0] if pages else await contexts[0].new_page()
            yield page
        finally:
            if browser is not None:
                try:
                    await browser.close()
                except BrowserError:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, 10)
                except subprocess.TimeoutExpired:
                    process.kill()

    async def _snapshot_page(self, page, url: str, include_html: bool = False) -> dict:
        """导航复用页面，出现目标 DOM、明确空态或访问拦截时立即读取快照。"""
        timeout_ms = round(self.settings.jobs_page_timeout_seconds * 1000)
        navigation_started_at = perf_counter()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except BrowserTimeoutError:
            # 某些页面的统计资源持续连接，但主体已经可读；继续检查业务 DOM。
            LOGGER.info("boss_navigation_domcontentloaded_timeout url=%s", url)
        readiness_markers = [
            *_DETAIL_MARKERS,
            *_NO_RESULT_MARKERS,
            *_VERIFY_MARKERS,
            *_LOGIN_MARKERS,
        ]
        try:
            await page.wait_for_function(
                r"""markers => {
                    const body = document.body?.innerText || '';
                    return Boolean(
                        document.querySelector('a[href*="/job_detail/"]') ||
                        document.querySelector('.job-sec-text, .job-detail-section, .job-detail-content') ||
                        markers.some(marker => body.includes(marker))
                    );
                }""",
                arg=readiness_markers,
                timeout=timeout_ms,
            )
        except BrowserTimeoutError:
            LOGGER.info("boss_business_dom_timeout url=%s", url)
        if self.settings.jobs_dom_stable_seconds:
            await self._sleep(self.settings.jobs_dom_stable_seconds)
        snapshot = await page.evaluate(
                    r"""includeHtml => {
                        const text = node => (node?.innerText || node?.textContent || '').replace(/\s+/g, ' ').trim();
                        const pick = (card, selectors) => {
                            for (const selector of selectors) {
                                const value = text(card?.querySelector(selector));
                                if (value) return value;
                            }
                            return '';
                        };
                        const rows = [...document.querySelectorAll('a[href*="/job_detail/"]')].map(anchor => {
                            const card = anchor.closest('li') || anchor.closest('.job-card-wrapper') || anchor.closest('[class*=job-card]') || anchor.parentElement;
                            return {
                                href: anchor.href,
                                title: pick(card, ['.job-name', '.job-title']) || anchor.title || text(anchor),
                                company: pick(card, ['.boss-name', '.company-name', '.company-text h3', '[class*=company-name]']),
                                salary: pick(card, ['.job-salary', '.salary', '[class*=salary]']),
                                location: pick(card, ['.company-location', '.job-area', '.job-location', '[class*=job-area]']),
                                summary: text(card),
                            };
                        });
                        const first = selectors => {
                            for (const selector of selectors) {
                                const value = text(document.querySelector(selector));
                                if (value) return value;
                            }
                            return '';
                        };
                        return {
                            url: location.href,
                            title: document.title,
                            body: document.body?.innerText || '',
                            rows,
                            detail: {
                                position_name: first(['h1', '.name h1', '.job-name']),
                                company_name: first(['.sider-company .company-info', '.company-name', '.company-info']),
                                salary: first(['span.salary', '.job-primary .salary']),
                                base_location: first(['.text-desc.text-city', '.job-primary .text-city']),
                            },
                            html: includeHtml ? document.documentElement.outerHTML : '',
                        };
                    }""",
                    include_html,
                )
        LOGGER.info(
            "boss_page_ready kind=%s elapsed_ms=%d url=%s",
            "detail" if include_html else "listing",
            round((perf_counter() - navigation_started_at) * 1000),
            snapshot["url"],
        )
        return snapshot

    @staticmethod
    async def _wait_for_debug_endpoint(endpoint: str, process) -> None:
        """等待 Chrome 本地调试端口；浏览器提前退出时立即报告。"""
        def ready() -> bool:
            try:
                with urllib.request.urlopen(endpoint + "/json/version", timeout=1) as response:
                    return response.status == 200
            except Exception:
                return False

        for _ in range(50):
            if process.poll() is not None:
                break
            if await asyncio.to_thread(ready):
                return
            await asyncio.sleep(0.2)
        raise ApplicationError(
            "BOSS_BROWSER_FAILED",
            "Chrome 本地调试端口未能启动，请关闭其他专用 BOSS 窗口后重试。",
            status_code=503,
        )

    @staticmethod
    def _raise_for_access_page(url: str, body: str) -> None:
        path = urlparse(url).path.lower()
        if any(token in path for token in ("security-check", "/security.", "/verify.", "/captcha")) or any(
            marker in body for marker in _VERIFY_MARKERS
        ):
            raise ApplicationError(
                "BOSS_VERIFICATION_REQUIRED",
                "BOSS 要求安全验证，请运行 start-boss-login.bat 手动完成后重试。",
                status_code=503,
            )
        if "/web/user/" in path or any(marker in body for marker in _LOGIN_MARKERS):
            raise ApplicationError(
                "BOSS_LOGIN_REQUIRED",
                "BOSS 登录状态已失效，请运行 start-boss-login.bat 重新登录。",
                status_code=503,
            )

    @staticmethod
    def _source_text(listing: dict, description: str) -> str:
        fields = [
            ("岗位", listing.get("position_name")),
            ("公司", listing.get("company_name")),
            ("地点", listing.get("base_location")),
            ("薪资", listing.get("salary")),
            ("列表摘要", listing.get("list_summary")),
        ]
        header = "\n".join(f"{name}：{value}" for name, value in fields if value)
        return (header + "\n\n详情页：\n" + description)[:30000]


def _clean_value(value) -> str:
    return _normalize_space(str(value or ""))


def _clean_salary(value) -> str:
    """丢弃列表页自定义字体映射的私用区字符，等待详情页真实文本回填。"""
    cleaned = _clean_value(value)
    if any("\ue000" <= character <= "\uf8ff" for character in cleaned):
        return ""
    return cleaned


def _clean_summary(value) -> str:
    """移除整段依赖 BOSS 自定义字体解码的薪资 token，避免输出私用区乱码。"""
    cleaned = _clean_value(value)
    tokens = cleaned.split()
    return " ".join(
        token
        for token in tokens
        if not any("\ue000" <= character <= "\uf8ff" for character in token)
    )


def _normalize_description(value: str) -> str:
    normalized = _normalize_space(value)
    normalized = re.sub(
        r"(?:^|\n)(?:BOSS直聘|boss|直聘)(?:\n|$)",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"岗\s*位\s*职\s*责\s*[:：]", "岗位职责：", normalized, count=1)
    normalized = re.sub(r"(^|\n)主要职责\s*[:：]?", r"\1岗位职责：", normalized, count=1)
    normalized = re.sub(r"(^|\n)工作内容\s*[:：]?", r"\1岗位职责：", normalized, count=1)
    return re.sub(r"(^|\n)职责\s*[:：]", r"\1岗位职责：", normalized, count=1)


def _normalize_space(value: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def _unique_text(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))
