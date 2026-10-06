"""推荐岗位偏好记忆的六轮触发、上下文注入与 SQLite 持久化测试。"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from backend.app.agent.context import ToolContextStore
from backend.app.agent.memory import JobPreferenceMemoryStore
from backend.app.agent.runtime import AgentRuntime
from backend.app.core.config import Settings
from backend.app.schemas.chat import ChatCompletionRequest


class MemoryProvider:
    def __init__(self, replies: list[str], summaries: list[str] | None = None):
        self.replies = iter(replies)
        self.summaries = iter(summaries or [])
        self.stream_requests = []
        self.structured_requests = []

    def ensure_configured(self):
        pass

    async def stream(self, messages, tools, **options):
        self.stream_requests.append({"messages": list(messages), "tools": tools, **options})
        yield {
            "choices": [{
                "index": 0,
                "delta": {"content": next(self.replies)},
                "finish_reason": "stop",
            }],
        }

    async def structured(self, instructions, data, schema):
        self.structured_requests.append({"instructions": instructions, "data": data})
        value = next(self.summaries)
        if isinstance(value, Exception):
            raise value
        return schema(summary=value)


def recommendation_request(settings: Settings, user_turns: int) -> ChatCompletionRequest:
    messages = []
    for turn in range(1, user_turns):
        messages.extend([
            {"role": "user", "content": f"第{turn}轮：我偏好后端岗位。"},
            {"role": "assistant", "content": f"第{turn}轮回复。"},
        ])
    messages.append({"role": "user", "content": f"第{user_turns}轮：希望在杭州工作。"})
    return ChatCompletionRequest(
        model=settings.agent_model_name,
        messages=messages,
        metadata={"page_context": "recommendations", "conversation_id": "memory-test"},
    )


class PreferenceMemoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "agent.sqlite3"
        self.settings = Settings(
            _env_file=None,
            deepseek_api_key=None,
            langgraph_sqlite_path=self.path,
        )
        self.memory = JobPreferenceMemoryStore(self.path)
        self.context = ToolContextStore(self.path)

    def runtime(self, provider):
        return AgentRuntime(
            self.settings,
            provider=provider,
            context_store=self.context,
            preference_memory_store=self.memory,
        )

    def test_sixth_turn_summarizes_and_persists_no_more_than_100_characters(self):
        provider = MemoryProvider(["已记录你的求职偏好。"], ["偏好杭州的后端研发岗位，重视稳定业务和合理薪资。"])
        asyncio.run(self.runtime(provider).complete(recommendation_request(self.settings, 6)))

        self.assertEqual(self.memory.read_summary(), "偏好杭州的后端研发岗位，重视稳定业务和合理薪资。")
        key = self.memory.conversation_key({
            "page_context": "recommendations", "conversation_id": "memory-test",
        })
        self.assertEqual(self.memory.read_progress(key), 6)
        payload = provider.structured_requests[0]["data"]
        self.assertEqual(payload["previous_summary"], "")
        self.assertEqual(len(payload["recent_six_turns"]), 12)
        self.assertEqual(payload["recent_six_turns"][-1]["role"], "assistant")

    def test_saved_memory_is_injected_and_next_update_uses_only_new_six_turns(self):
        first = MemoryProvider(["第六轮回复。"], ["偏好杭州后端岗位。"])
        asyncio.run(self.runtime(first).complete(recommendation_request(self.settings, 6)))

        seventh = MemoryProvider(["第七轮回复。"])
        asyncio.run(self.runtime(seventh).complete(recommendation_request(self.settings, 7)))
        system_messages = [
            item["content"] for item in seventh.stream_requests[0]["messages"]
            if item["role"] == "system"
        ]
        self.assertTrue(any("偏好杭州后端岗位" in content for content in system_messages))
        self.assertEqual(seventh.structured_requests, [])

        twelfth = MemoryProvider(["第十二轮回复。"], ["偏好杭州后端岗位，也接受平台工程。"])
        asyncio.run(self.runtime(twelfth).complete(recommendation_request(self.settings, 12)))
        payload = twelfth.structured_requests[0]["data"]
        self.assertEqual(payload["previous_summary"], "偏好杭州后端岗位。")
        self.assertEqual(len(payload["recent_six_turns"]), 12)
        self.assertIn("第7轮", payload["recent_six_turns"][0]["content"])
        self.assertIn("第十二轮回复", payload["recent_six_turns"][-1]["content"])
        self.assertEqual(self.memory.read_summary(), "偏好杭州后端岗位，也接受平台工程。")

    def test_memory_store_rejects_oversized_summary(self):
        with self.assertRaises(ValueError):
            self.memory.save("conversation", "偏" * 101, 6)

    def test_memory_failure_does_not_break_agent_reply(self):
        provider = MemoryProvider(["正常回复。"], [RuntimeError("summary failed")])
        response = asyncio.run(
            self.runtime(provider).complete(recommendation_request(self.settings, 6))
        )
        self.assertEqual(response["choices"][0]["message"]["content"], "正常回复。")
        self.assertEqual(self.memory.read_summary(), "")


if __name__ == "__main__":
    unittest.main()
