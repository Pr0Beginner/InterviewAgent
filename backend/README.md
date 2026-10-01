# Backend

## 安装

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
```

## 启动

```powershell
.\start.bat
```

该脚本从项目根目录统一启动后端和 PySide6 客户端。

健康检查：`GET http://127.0.0.1:8000/api/health`

接口文档：`http://127.0.0.1:8000/docs`

当前已实现：

- `GET /api/interviews`：筛选、分页查询投递状态和状态汇总
- `POST /api/interviews`：新增投递记录
- `PATCH /api/interviews/{interview_id}`：保存整行修改
- `PATCH /api/interviews/{interview_id}/status`：单独更新投递状态
- `POST /v1/chat/completions`：OpenAI 兼容 Agent 对话，支持 JSON 与 SSE
- `GET /v1/models`：查询 Agent 模型名
- `POST /api/email/sync`、`GET /api/tasks/{task_id}`：按未读、已读或全部范围扫描邮件和查询进度
- `POST /api/feishu/sync`：同步飞书汇总
- `POST /api/job-recommendations`、`GET /api/job-recommendations/{id}`：真实岗位匹配、分页和 JD
- `POST /api/mock-interviews`、`GET /api/mock-interviews/{id}`：创建和恢复面试
- `POST /api/mock-interviews/{id}/answers`、`POST /api/mock-interviews/{id}/finish`：回答、追问和总结

## DeepSeek 配置

在现有 `backend/.env` 中填写以下配置，然后重启服务端；不要覆盖已有 MySQL 配置。

```dotenv
DEEPSEEK_API_KEY=你的DeepSeek密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
AGENT_MODEL_NAME=interview-assistant
AGENT_TIMEOUT_SECONDS=120
AGENT_MAX_TOOL_ROUNDS=4
```

`DEEPSEEK_MODEL` 可改为账户可用的模型名。客户端只访问本项目 Agent，不接触 DeepSeek 密钥。旧 `OPENAI_API_KEY` 不再被程序读取。

调用本地 Agent 示例：

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="local")
stream = client.chat.completions.create(
    model="interview-assistant",
    messages=[{"role": "user", "content": "网易目前是什么面试状态？"}],
    metadata={"page_context": "applications"},
    stream=True,
)
for chunk in stream:
    if chunk.choices:
        print(chunk.choices[0].delta.content or "", end="")
```

本地接口当前未启用鉴权，SDK 的 `api_key="local"` 仅用于满足 SDK 参数要求。默认监听 `127.0.0.1`。

查询、更新业务图已接入 LangGraph，检查点保存在 SQLite；业务变更、状态历史和飞书待同步项在同一 MySQL 事务中提交。对话历史由客户端按 Tab 携带；SQLite 另存每个会话最近的面试/题目/邮件任务 ID，供 ReAct 后续调用。

## 外部连接配置

配置均位于 `backend/.env`，修改后重启服务端。

| 配置 | 内容 |
|---|---|
| `FEISHU_InterviewDate_TOKEN` | 面试安排多维表格 Wiki 链接，保留 table 和 view 参数 |
| `FEISHU_Progress_TOKEN` | 进度文档链接，自动定位文档内嵌的电子表格 |
| `FEISHU_InterviewQuestion_TOKEN` | 面经或面经索引文档链接，只读取 ZMY 标题下的正文 |
| `FEISHU_CLI_PATH` | 默认 `lark-cli`，自动找到本机安装并复用当前用户登录态 |
| `FEISHU_NODE_PATH` | 默认 `node`；Windows 隐藏服务可配置绝对路径，避免继承到不同 Node.js 环境 |
| `FEISHU_CLI_PROFILE` | 可选；固定已经完成用户授权的 CLI Profile，避免服务进程选中其他 Profile |
| `NETEASE_EMAIL` | 网易邮箱地址 |
| `NETEASE_EMAIL_AUTH_CODE` | 开启 IMAP 后的客户端授权码 |
| `NETEASE_IMAP_HOST` | 默认 `imap.163.com`；126 邮箱使用 `imap.126.com` |
| `BOSS_BROWSER_CHANNEL` | 默认 `msedge`，使用本机 Edge |
| `BOSS_PROFILE_PATH` | 默认 `backend/data/boss-profile`，专用浏览器登录资料，不提交到代码库 |
| `JOBS_MAX_CANDIDATES` | 单次读取候选数，默认 10 |
| `MOCK_INTERVIEW_MAX_QUESTIONS` | 每场最多题数，默认 8 |

BOSS 登录使用根目录 `start-boss-login.bat`。遇到验证请在该窗口手动完成，不绕过验证；没有真实 JD 不生成假岗位。分页复用已存结果，“重新匹配”才发起新搜索。

飞书读取原进度表的单位、部门、地点、状态、结果，按实际行号定位。同步默认导入明确状态及日期，再推送本地待同步项；状态或记录匹配不明确时返回待核对项或冲突，不重建原表。新投递尚未在原表唯一定位时保留待同步，请先补齐飞书记录；原表没有岗位链接列，链接继续留在 MySQL，不擅自扩展列。

“已投递”表示简历已投出但尚未收到笔试或面试邀请。“待面试”表示收到面试邀请但尚未参加，是正常状态；日期表只补充邀请时间，不把它改写为已经参加的一面或二面。日期更新仅修改唯一对应的已有安排，不覆盖其他轮次、结束时间或其他记录。进度及日期没有跨系统原子事务，失败保留待同步项，重试前回读检查冲突。

面经先取目录定位 ZMY，配置为索引时仅跟随“面经”下的文档引用；找不到唯一 ZMY 就报错，不退化为读取整篇。模拟面试和 Agent 面经工具复用这个范围限制。

邮箱正文只用于当次模型提取，不进入数据库和图检查点。自动更新仅接受明确通知、唯一匹配的已有投递；含糊、跨终态或倒退事件保留未读供人工处理。

本项目按本地单进程运行；不要配置多个 Uvicorn workers。邮件处理中断后可重新扫描，处理标识和业务幂等记录防止重复修改。

接入验证（2026-09-30，只读）：飞书可读取 10 条进度、22 条安排及 ZMY 的 5 组面经；网易 IMAP 登录、未读查询、PEEK 正文读取及重复查询通过，未改变已读状态。BOSS 普通 HTTP 返回页面壳、0 条岗位链接；未登录浏览器探测发生跳转并落到空白页，尚未验证已登录岗位采集成功，不能把这种结果返回为推荐岗位。

验证命令：在项目根目录运行 `.venv\Scripts\python.exe -m scripts.check_integrations`；追加 `--boss` 会额外使用临时浏览器检查一次公开页面，不读取用户 Cookie。BOSS 登录脚本只打开一次首页，不循环刷新；网站自身跳转或验证仍需人工处理。[Playwright 认证与登录态复用](https://playwright.dev/python/docs/auth)。

协议参考：[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat)、[DeepSeek API](https://api-docs.deepseek.com/zh-cn/)。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
```

需要实际调用 DeepSeek 时，手动运行以下脚本（会消耗 API 额度）：

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_agent
.\.venv\Scripts\python.exe -m scripts.smoke_business
```

前者只读实际投递记录；后者使用临时数据库验证新增、修改、模拟面试、合成邮件与 JD 提取，不访问实际邮箱或写入飞书。

## 数据库迁移

配置 `backend/.env` 中的 `MYSQL_URL` 后执行：

```powershell
.\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
```

迁移创建以下业务表：

- `job_applications`：投递记录当前状态
- `application_status_history`：每次状态变化的历史记录
- `agent_operations`：业务写入幂等凭据、飞书导出快照
- `feishu_sync_items`：飞书待同步记录
- `email_receipts`：邮件处理标识，不保存正文
- `task_runs`：邮件任务进度和岗位搜索快照
- `mock_interview_sessions`：模拟面试上下文、回答和总结
