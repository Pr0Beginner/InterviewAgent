# Backend

## 安装与启动

在项目根目录执行：

```bat
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
copy backend\.env.example backend\.env
start.bat
```

- 健康检查：`GET http://127.0.0.1:8000/api/health`
- 接口文档：`http://127.0.0.1:8000/docs`

## 已实现接口

- `GET /api/interviews`：筛选、分页查询投递记录和状态汇总
- `POST /api/interviews`：新增投递记录
- `PATCH /api/interviews/{interview_id}`：保存整行修改
- `PATCH /api/interviews/{interview_id}/status`：单独更新投递状态
- `POST /v1/chat/completions`：OpenAI 兼容 Agent 对话，支持 JSON 与 SSE
- `GET /v1/models`：查询 Agent 模型名
- `POST /api/email/sync`、`GET /api/tasks/{task_id}`：扫描邮件和查询异步任务进度
- `POST /api/job-recommendations`、`GET /api/job-recommendations/{id}`：岗位匹配、分页和 JD
- `POST /api/mock-interviews`、`GET /api/mock-interviews/{id}`：创建和恢复模拟面试
- `POST /api/mock-interviews/resumes`：上传并解析 PDF/DOCX 简历，文本仅保存在本地
- `POST /api/mock-interviews/{id}/answers`、`POST /api/mock-interviews/{id}/finish`：回答、追问和总结

## 配置

配置均位于 `backend/.env`，修改后重启服务端。

| 配置 | 内容 |
|---|---|
| `INTERVIEWS_FILE_PATH` | 投递记录 Markdown 文件，默认 `data/interviews.md` |
| `LOCAL_STATE_PATH` | 运行状态 JSON 文件，默认 `data/runtime.json` |
| `LANGGRAPH_SQLITE_PATH` | LangGraph 检查点文件，默认 `data/langgraph.sqlite3` |
| `RESUME_STORAGE_PATH` | 简历解析文本目录，默认 `data/resumes` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | DeepSeek 模型名 |
| `LANGFUSE_ENABLED` | 是否开启 Langfuse，可选，默认 `false` |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Langfuse 项目凭据 |
| `LANGFUSE_BASE_URL` | Langfuse Cloud 区域地址或自托管地址 |
| `LANGFUSE_TRACING_ENVIRONMENT` | 观测环境名，例如 `development`、`production` |
| `LANGFUSE_SAMPLE_RATE` | Trace 采样率，范围 `0` 到 `1` |
| `LANGFUSE_CAPTURE_CONTENT` | 是否上传受限正文；默认 `false`，只上传摘要 |
| `NETEASE_EMAIL` | 网易邮箱地址 |
| `NETEASE_EMAIL_AUTH_CODE` | 开启 IMAP 后的客户端授权码 |
| `NETEASE_IMAP_HOST` | 默认 `imap.163.com`；126 邮箱使用 `imap.126.com` |
| `BOSS_BROWSER_CHANNEL` | 默认 `chrome`，使用本机 Google Chrome |
| `BOSS_PROFILE_PATH` | BOSS 专用浏览器登录资料目录 |
| `JOBS_MAX_CANDIDATES` | 单次读取候选数，默认 10 |
| `JOBS_PAGES_PER_QUERY` | 每个城市和关键词最多读取的列表页数，默认 2 |
| `JOBS_MAX_SEARCH_PAGES` | 单次搜索最多请求的列表页总数，默认 6 |
| `JOBS_PAGE_TIMEOUT_SECONDS` | 单个 BOSS 页面等待业务 DOM 的最大秒数，默认 15 |
| `JOBS_DOM_STABLE_SECONDS` | 业务 DOM 出现后用于吸收末尾渲染的短暂等待，默认 0.5 |
| `JOBS_REQUEST_INTERVAL_SECONDS` | BOSS 页面请求最小间隔，默认 3 秒，不能低于 1 秒 |
| `MOCK_INTERVIEW_MAX_QUESTIONS` | 每场最多题数，默认 8 |

本地接口未启用鉴权，只监听 `127.0.0.1`。客户端只访问本项目服务端，不接触 DeepSeek 密钥。

Langfuse 的项目密钥从项目 **Settings → API Keys** 获取，只应配置在服务端 `backend/.env`。开启后会通过官方 OpenAI 包装器记录 DeepSeek generation，并用 `conversation_id` 聚合同一会话；默认隐私模式不会上传提示词和回答正文。

## 本地存储

| 文件 | 用途 |
|---|---|
| `data/interviews.md` | 投递记录，是投递页面和 Agent 查询/修改的唯一业务数据源 |
| `data/runtime.json` | 邮件处理标识、异步任务、岗位缓存和模拟面试上下文 |
| `data/langgraph.sqlite3` | LangGraph 图检查点和工具上下文 |
| `data/resumes/*.txt` | 简历提取后的纯文本；面试会话只保存简历 ID，不复制正文 |

`MarkdownInterviewStore` 负责投递记录的分页、筛选、排序和原子写入；`LocalStateStore` 负责运行状态的加锁与原子写入。项目按本地单进程运行，不要配置多个 Uvicorn workers。

邮箱正文只用于当次模型提取，不写入本地文件或图检查点。自动更新仅接受明确通知和唯一匹配的已有投递；含糊事件进入人工核对结果。

BOSS 登录使用根目录 `start-boss-login.bat`。遇到验证请手动完成，不绕过验证；没有真实 JD 时不生成假岗位。分页复用已保存结果，“重新匹配”才发起新搜索。

也可以单独运行低频学习脚本并将结果输出为 JSON：

```bat
.venv\Scripts\python.exe -m scripts.crawl_boss_jobs --keyword Java --keyword 后端 --city 杭州 --experience 应届生 --limit 5
```

脚本按“城市 → 关键词 → 页码”执行有限搜索，使用岗位 URL 去重，并在详情请求之间等待。它复用专用登录资料，不处理或绕过验证码。

## Agent 协议

本地 Agent 使用 OpenAI Chat Completions 兼容协议：

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="local")
response = client.chat.completions.create(
    model="interview-assistant",
    messages=[{"role": "user", "content": "网易目前是什么面试状态？"}],
    metadata={"page_context": "applications"},
)
print(response.choices[0].message.content)
```

查询和更新投递记录使用 LangGraph 业务图，检查点保存在 SQLite；业务数据始终读取和写入 Markdown。对话历史由客户端按 Tab 携带。

## 测试

```bat
.venv\Scripts\python.exe -m unittest discover -s backend\tests
```

需要实际调用 DeepSeek 时，可手动运行以下脚本；它们会消耗 API 额度：

```bat
.venv\Scripts\python.exe -m scripts.smoke_agent
.venv\Scripts\python.exe -m scripts.smoke_business
```
