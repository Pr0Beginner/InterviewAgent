"""使用本地模拟模型服务测试真实 OpenAI SDK，不消耗 API 额度。"""

import json
import asyncio
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from backend.app.agent.provider import DeepSeekProvider
from backend.app.core.config import Settings


class DeepSeekProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_langfuse_uses_official_openai_wrapper(self):
        captured = {}

        class FakeStream:
            def __init__(self):
                self.sent = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.sent:
                    raise StopAsyncIteration
                self.sent = True
                return SimpleNamespace(model_dump=lambda **_: {
                    "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
                })

        class FakeCompletions:
            async def create(self, **values):
                captured["completion"] = values
                return FakeStream()

        class FakeAsyncOpenAI:
            def __init__(self, **values):
                captured["client"] = values
                self.chat = SimpleNamespace(completions=FakeCompletions())

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

        fake_module = ModuleType("langfuse.openai")
        fake_module.AsyncOpenAI = FakeAsyncOpenAI
        settings = Settings(
            _env_file=None,
            deepseek_api_key="test-only",
            langfuse_enabled=True,
            langfuse_public_key="pk-test",
            langfuse_secret_key="sk-test",
        )
        provider = DeepSeekProvider(settings)
        with patch("backend.app.agent.provider.get_langfuse", return_value=object()), \
                patch.dict(sys.modules, {"langfuse.openai": fake_module}):
            chunks = [chunk async for chunk in provider.stream(
                [{"role": "user", "content": "hello"}], [], temperature=0.2, max_tokens=50,
            )]

        self.assertEqual(chunks[0]["choices"][0]["delta"]["content"], "ok")
        self.assertEqual(captured["completion"]["name"], "generate-agent-response")
        self.assertEqual(captured["completion"]["langfuse_public_key"], "pk-test")
        self.assertEqual(captured["completion"]["metadata"]["provider"], "deepseek")

    async def test_sdk_sends_deepseek_settings_and_parses_sse(self):
        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured["path"] = self.path
                captured["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                captured["authorization"] = self.headers["Authorization"]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                chunk = {
                    "id": "fixture", "object": "chat.completion.chunk", "created": 0,
                    "model": "configured-test-model", "choices": [{
                        "index": 0, "delta": {"content": "连接成功"}, "finish_reason": "stop",
                    }],
                }
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = DeepSeekProvider(Settings(
                _env_file=None, deepseek_api_key="test-only",
                deepseek_base_url=f"http://127.0.0.1:{server.server_port}",
                deepseek_model="configured-test-model",
            ))
            chunks = [chunk async for chunk in provider.stream(
                [{"role": "user", "content": "hello"}], [], temperature=0.2, max_tokens=50,
            )]
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(captured["path"], "/chat/completions")
        self.assertEqual(captured["body"]["model"], "configured-test-model")
        self.assertEqual(captured["body"]["thinking"]["type"], "disabled")
        self.assertEqual(captured["authorization"], "Bearer test-only")
        self.assertEqual(chunks[0]["choices"][0]["delta"]["content"], "连接成功")


if __name__ == "__main__":
    unittest.main()
