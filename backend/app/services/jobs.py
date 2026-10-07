"""使用 Skill 对真实 JD 进行匹配排序，并缓存结果以保持分页稳定。"""

import asyncio
from hashlib import sha256
import json
import logging
from time import perf_counter
from uuid import uuid4

from backend.app.agent.provider import DeepSeekProvider
from backend.app.agent.memory import JobPreferenceMemoryStore
from backend.app.agent.skills import load_skill
from backend.app.core.config import get_settings
from backend.app.core.exceptions import ApplicationError
from backend.app.integrations.boss import BossJobSource
from backend.app.schemas.business import JobAssessmentBatch
from backend.app.storage.local import LocalStateStore

SKILL = load_skill("job-recommendation")
MODEL_JD_CHARACTER_LIMIT = 12000
LOGGER = logging.getLogger(__name__)


class JobService:
    """获取来源页面，仅评估具有真实链接和 JD 文本的岗位。"""

    def __init__(self, state_store=None, provider=None, source=None, preference_memory_store=None):
        """注入本地状态文件、匹配评估模型和 BOSS 浏览器数据源。"""
        self.state_store = state_store or LocalStateStore()
        self.provider = provider or DeepSeekProvider(get_settings())
        self.source = source or BossJobSource()
        self.preference_memory_store = preference_memory_store or JobPreferenceMemoryStore(
            get_settings().langgraph_sqlite_path
        )

    async def recommend(self, request) -> dict:
        """创建或复用搜索快照，后续翻页不重复调用模型。"""
        started_at = perf_counter()
        criteria = request.model_dump(exclude={"page", "page_size", "extensions"})
        preference_summary = await asyncio.to_thread(
            self.preference_memory_store.read_summary
        )
        if preference_summary:
            criteria["preference_memory"] = preference_summary
        cache_id = "jobs-" + sha256(json.dumps(criteria, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:50]
        cached = self.state_store.get("job_searches", cache_id)
        items = cached.get("result", {}).get("items") if cached and cached.get("status") == "completed" else None
        if request.extensions.get("cached_only") and items is None:
            return self._page([], request, cache_id, "尚无匹配结果，点击重新匹配开始搜索。")
        if items is None or (request.extensions.get("refresh") and not request.extensions.get("cached_only")):
            self.provider.ensure_configured()
            source_started_at = perf_counter()
            sources = await self.source.search(
                request.keywords or request.tech_stack,
                get_settings().jobs_max_candidates,
                cities=request.cities,
                work_experience=request.work_experience,
            )
            source_elapsed = perf_counter() - source_started_at
            assessment_started_at = perf_counter()
            batch = await self.provider.structured(SKILL, {
                "task": "批量评估全部岗位；每个 source_index 必须且只能返回一次",
                "profile": criteria,
                "sources": [
                    {
                        "source_index": index,
                        **source,
                        "job_description": source["job_description"][:MODEL_JD_CHARACTER_LIMIT],
                    }
                    for index, source in enumerate(sources)
                ],
            }, JobAssessmentBatch)
            assessment_elapsed = perf_counter() - assessment_started_at
            assessments = {item.source_index: item for item in batch.items}
            expected_indexes = set(range(len(sources)))
            if set(assessments) != expected_indexes:
                raise ApplicationError(
                    "JOB_ASSESSMENT_INCOMPLETE",
                    "模型未完整返回岗位分析，请重试。",
                    status_code=502,
                    details={
                        "expected": sorted(expected_indexes),
                        "received": sorted(assessments),
                    },
                )
            items = []
            for source_index, source in enumerate(sources):
                assessment = assessments[source_index]
                item = assessment.model_dump()
                item.pop("source_index")
                if request.cities and not any(city in item["base_location"] for city in request.cities):
                    continue
                item.update(
                    id="job-" + uuid4().hex,
                    job_url=source["job_url"],
                    job_description=source["job_description"],
                    salary=source.get("salary") or "待确认",
                )
                items.append(item)
            items.sort(key=lambda item: item["match_score"], reverse=True)
            self.state_store.put("job_searches", cache_id, {
                "id": cache_id,
                "status": "completed",
                "result": {"criteria": criteria, "items": items},
            })
            LOGGER.info(
                "job_recommendation_complete cache_hit=false sources=%s results=%s source_ms=%d assessment_ms=%d total_ms=%d",
                len(sources),
                len(items),
                round(source_elapsed * 1000),
                round(assessment_elapsed * 1000),
                round((perf_counter() - started_at) * 1000),
            )
        else:
            LOGGER.info(
                "job_recommendation_complete cache_hit=true results=%s total_ms=%d",
                len(items),
                round((perf_counter() - started_at) * 1000),
            )
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
