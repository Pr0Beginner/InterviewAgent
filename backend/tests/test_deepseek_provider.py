"""使用本地模拟模型服务测试真实 OpenAI SDK，不消耗 API 额度。"""

import json
import asyncio
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from backend.app.agent.provider import DeepSeekProvider
from backend.app.core.config import Settings


class DeepSeekProviderTest(unittest.IsolatedAsyncioTestCase):
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
