"""只读的真实环境冒烟测试。需手动运行 python -m scripts.smoke_agent。"""

import json
from time import perf_counter

from fastapi.testclient import TestClient

from backend.app.agent.runtime import AgentRuntime
from backend.app.agent.tools import execute_tool
from backend.app.api.routes.chat import get_agent_runtime
from backend.app.core.config import get_settings
from backend.app.main import create_app


def main() -> None:
    """使用受限提示词调用已配置的模型供应商，不执行业务写入。"""
    settings = get_settings()
    settings.agent_timeout_seconds = 60
    calls = []

    def read_only_tool(name, arguments):
        """真实环境冒烟测试仅允许调用查询工具。"""
        calls.append(name)
        if name != "query_interview_status":
            return {"error": "Live smoke tests permit read-only queries only."}
        return execute_tool(name, arguments)

    app = create_app()
    app.dependency_overrides[get_agent_runtime] = lambda: AgentRuntime(settings, tool_executor=read_only_tool)
    with TestClient(app) as client:
        for label, message, stream in [
            ("chat", "请只回复：连接正常", False),
            ("stream", "请只回复：流式正常", True),
            ("query", "请调用工具查询我当前的投递记录总数，只回复总数，不要修改数据。", False),
        ]:
            started = perf_counter()
            response = client.post("/v1/chat/completions", json={
                "model": settings.agent_model_name, "messages": [{"role": "user", "content": message}],
                "stream": stream, "max_tokens": 400,
                "metadata": {"page_context": "applications"},
            })
            result = {"check": label, "http_status": response.status_code, "seconds": round(perf_counter() - started, 2)}
            if response.status_code != 200:
                result["error"] = response.json().get("error")
            elif stream:
                frames = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
                chunks = [json.loads(frame) for frame in frames if frame != "[DONE]"]
                result["done"] = bool(frames and frames[-1] == "[DONE]")
                result["errors"] = [chunk["error"] for chunk in chunks if "error" in chunk]
                result["reply"] = "".join(choice.get("delta", {}).get("content", "") for chunk in chunks for choice in chunk.get("choices", []))
            else:
                result["reply"] = response.json()["choices"][0]["message"]["content"]
            print(json.dumps(result, ensure_ascii=False), flush=True)
    print(json.dumps({"tool_calls": calls}, ensure_ascii=False))


if __name__ == "__main__":
    main()
