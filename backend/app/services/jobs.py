"""使用 Skill 对真实 JD 进行匹配排序，并缓存结果以保持分页稳定。"""

from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from backend.app.agent.provider import DeepSeekProvider
from backend.app.core.config import get_settings
from backend.app.core.exceptions import ApplicationError
from backend.app.integrations.boss import BossJobSource
from backend.app.schemas.business import JobAssessment
from backend.app.storage.local import LocalStateStore

SKILL = (Path(__file__).resolve().parents[1] / "agent/skills/job_recommendation.md").read_text(encoding="utf-8")


class JobService:
    """获取来源页面，仅评估具有真实链接和 JD 文本的岗位。"""

    def __init__(self, state_store=None, provider=None, source=None):
        """注入本地状态文件、匹配评估模型和 BOSS 浏览器数据源。"""
        self.state_store = state_store or LocalStateStore()
        self.provider = provider or DeepSeekProvider(get_settings())
        self.source = source or BossJobSource()

    async def recommend(self, request) -> dict:
        """创建或复用搜索快照，后续翻页不重复调用模型。"""
        criteria = request.model_dump(exclude={"page", "page_size", "extensions"})
        cache_id = "jobs-" + sha256(json.dumps(criteria, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:50]
        cached = self.state_store.get("job_searches", cache_id)
        items = cached.get("result", {}).get("items") if cached and cached.get("status") == "completed" else None
        if request.extensions.get("cached_only") and items is None:
            return self._page([], request, cache_id, "尚无匹配结果，点击重新匹配开始搜索。")
        if items is None or (request.extensions.get("refresh") and not request.extensions.get("cached_only")):
            self.provider.ensure_configured()
            sources = await self.source.search(request.keywords or request.tech_stack, get_settings().jobs_max_candidates)
            items = []
            # 限制数量并串行调用模型，避免瞬时请求过多，同时便于取消。
            for source in sources:
                assessment = await self.provider.structured(SKILL, {"profile": criteria, "source": source}, JobAssessment)
                item = assessment.model_dump()
                if request.cities and not any(city in item["base_location"] for city in request.cities):
                    continue
                item.update(id="job-" + uuid4().hex, job_url=source["job_url"], job_description=source["job_description"])
                items.append(item)
            items.sort(key=lambda item: item["match_score"], reverse=True)
            self.state_store.put("job_searches", cache_id, {
                "id": cache_id,
                "status": "completed",
                "result": {"criteria": criteria, "items": items},
            })
        return self._page(items, request, cache_id)

    def get(self, recommendation_id: str) -> dict:
        """在已持久化的搜索快照中查找推荐记录。"""
        for row in self.state_store.values("job_searches"):
            if row.get("status") != "completed":
                continue
            for job in row.get("result", {}).get("items", []):
                if job["id"] == recommendation_id:
                    return job
        raise ApplicationError("JOB_NOT_FOUND", "岗位推荐不存在或已刷新。", status_code=404)

    @staticmethod
    def _page(items, request, search_id, message=None):
        """按前端统一的分页格式返回指定搜索快照的数据。"""
        total = len(items)
        total_pages = max(1, (total + request.page_size - 1) // request.page_size)
        start = (request.page - 1) * request.page_size
        return {"items": items[start:start + request.page_size], "total": total,
                "page": request.page, "page_size": request.page_size, "total_pages": total_pages,
                "has_previous": request.page > 1, "has_next": request.page < total_pages,
                "search_id": search_id, "message": message}
