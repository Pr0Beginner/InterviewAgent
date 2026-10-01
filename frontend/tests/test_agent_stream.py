import json
import unittest

import httpx

from client.api.hybrid_api import ApiRequestError, HybridApiClient


def event(content="", finish=None):
    return {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": finish}]}


def sse(*items):
    return "".join("data: " + (item if isinstance(item, str) else json.dumps(item)) + "\n\n" for item in items)


class AgentStreamTest(unittest.IsolatedAsyncioTestCase):
    def api(self, body, captured=None, status=200):
        def handler(request):
            if captured is not None:
                captured.append(request)
            return httpx.Response(status, text=body, headers={"content-type": "text/event-stream"})
        api = HybridApiClient("http://testserver/api", transport=httpx.MockTransport(handler))
        self.addCleanup(api.close)
        return api

    async def test_stream_uses_agent_endpoint_and_sends_history_and_tab(self):
        requests = []
        api = self.api(sse(event("你好"), event(finish="stop"), "[DONE]"), requests)
        messages = [{"role": "user", "content": "查询"}]
        chunks = [chunk async for chunk in api.stream_chat_completion(messages, metadata={"page_context": "applications"}, extensions={"future": 1})]
        self.assertEqual(requests[0].url.path, "/v1/chat/completions")
        body = json.loads(requests[0].content)
        self.assertEqual(body["messages"], messages)
        self.assertEqual(body["metadata"]["page_context"], "applications")
        self.assertEqual(body["extensions"], {"future": 1})
        self.assertEqual(chunks[0]["choices"][0]["delta"]["content"], "你好")

    async def test_partial_stream_does_not_become_success(self):
        for body in (sse(event("部分")), sse(event("部分"), "[DONE]"), sse({"error": {"message": "模型不可用"}}, "[DONE]")):
            with self.subTest(body=body):
                api = self.api(body)
                with self.assertRaises(ApiRequestError):
                    _ = [chunk async for chunk in api.stream_chat_completion([{"role": "user", "content": "测试"}])]

    async def test_missing_key_error_is_visible(self):
        api = self.api(json.dumps({"error": {"message": "请配置 DEEPSEEK_API_KEY"}}), status=503)
        with self.assertRaisesRegex(ApiRequestError, "DEEPSEEK_API_KEY"):
            _ = [chunk async for chunk in api.stream_chat_completion([{"role": "user", "content": "测试"}])]


if __name__ == "__main__":
    unittest.main()
