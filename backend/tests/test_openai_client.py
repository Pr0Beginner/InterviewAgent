"""验证未经修改的 OpenAI SDK 可以调用本项目 Agent 接口。"""

import socket
import threading
import time
import unittest

import uvicorn
from openai import DefaultHttpxClient, OpenAI

from backend.app.agent.runtime import AgentRuntime
from backend.app.api.routes.chat import get_agent_runtime
from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.tests.test_agent_api import FakeProvider, native_chunk


class OpenAIClientCompatibilityTest(unittest.TestCase):
    def test_sdk_models_json_and_sse_against_agent(self):
        app = create_app()
        settings = Settings(_env_file=None, deepseek_api_key=None)
        app.dependency_overrides[get_agent_runtime] = lambda: AgentRuntime(
            settings, FakeProvider([[native_chunk({"content": "测试回复"}, "stop")]]),
        )
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(server.started)
            with OpenAI(
                api_key="local", base_url=f"http://127.0.0.1:{port}/v1",
                max_retries=0, timeout=5,
                http_client=DefaultHttpxClient(trust_env=False),
            ) as client:
                self.assertEqual(client.models.list().data[0].id, "interview-assistant")
                kwargs = {
                    "model": "interview-assistant",
                    "messages": [{"role": "user", "content": "你好"}],
                    "metadata": {"page_context": "applications"},
                    "extra_body": {"extensions": {"future": True}},
                }
                response = client.chat.completions.create(**kwargs)
                self.assertEqual(response.choices[0].message.content, "测试回复")
                with client.chat.completions.create(**kwargs, stream=True) as stream:
                    text = "".join(chunk.choices[0].delta.content or "" for chunk in stream if chunk.choices)
                self.assertEqual(text, "测试回复")
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            listener.close()
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
