# Interview Assistant

Interview Assistant 是一个面向个人秋招管理的桌面 Agent。它将投递进度、招聘邮件、飞书记录、岗位推荐和模拟面试集中到一个客户端中，并允许通过自然语言查询或更新求职状态。

> 项目默认只监听本机地址，适合作为个人工具运行。BOSS 直聘功能只负责读取岗位并给出推荐，不会自动投递。

## 核心功能

| 功能 | 说明 |
|---|---|
| Agent 对话 | 根据当前页面调用对应工具，支持流式输出和 Markdown 展示 |
| 投递管理 | 分页查询、筛选和直接编辑公司、岗位、Base、状态及面试时间 |
| 邮件扫描 | 扫描网易邮箱中的未读、已读或全部邮件，提取笔试、面试、Offer 和拒信信息 |
| 飞书同步 | 从飞书进度表与日期表读取记录，并将本地修改同步回原表 |
| 岗位推荐 | 从 BOSS 直聘读取真实岗位，按照技术栈、业务方向和 Base 地给出匹配度 |
| 模拟面试 | 根据目标公司、岗位、轮次及个人面经逐题提问，并生成面试总结 |

系统支持以下投递状态：

```text
已投递、简历筛选中、笔试中、待面试、一面、二面、三面、HR面、Offer、已结束
```

- `已投递`：简历已经投出，但尚未收到笔试或面试邀请。
- `待面试`：已经收到面试邀请，但面试尚未进行，是正常业务状态。

## 系统架构

![Interview Assistant 系统架构](docs/秋招Agent-系统架构图.png)

### 技术栈

| 模块 | 技术 |
|---|---|
| 桌面客户端 | Python、PySide6、httpx |
| 服务端 | Python、FastAPI、Pydantic |
| Agent | LangGraph、ReAct、OpenAI 兼容协议、DeepSeek API |
| 业务数据库 | MySQL、SQLAlchemy、Alembic |
| Agent 状态 | SQLite |
| 外部接入 | 飞书 CLI、网易邮箱 IMAP、Playwright、BOSS 直聘 |

## 项目结构

```text
InterviewAssistant/
├─ frontend/                 # PySide6 客户端及前端测试
├─ backend/
│  ├─ app/                   # FastAPI、Agent、业务服务及外部连接器
│  ├─ migrations/            # Alembic 数据库迁移
│  ├─ tests/                 # 后端测试
│  └─ .env.example           # 配置模板，不包含密钥
├─ scripts/                  # 启动、接入检查和冒烟测试脚本
├─ docs/                     # 设计图和界面预览
├─ start.bat                 # 一键启动前后端
├─ start-boss-login.bat      # 初始化 BOSS 专用浏览器登录态
├─ CLIENT_DESIGN.md          # 客户端设计
└─ SERVER_DESIGN.md          # 服务端、Agent 和接口设计
```

## 环境要求

- Windows 10/11
- Python 3.11 或 3.12
- MySQL 8.x
- Microsoft Edge（岗位读取使用）
- DeepSeek API Key（使用 Agent 时需要）
- 飞书 CLI 与 Node.js（使用飞书同步时需要）
- 已开启 IMAP 的网易邮箱及客户端授权码（使用邮件扫描时需要）

飞书、网易邮箱和 BOSS 均为可选接入；未配置时不影响投递表格等基础功能。

## 安装

### 创建虚拟环境并安装依赖

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item backend\.env.example backend\.env
```

### 创建 MySQL 数据库

使用自己的 MySQL 管理账号执行：

```sql
CREATE DATABASE interview_assistant
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'interview'@'localhost' IDENTIFIED BY '请替换为自己的强密码';
GRANT ALL PRIVILEGES ON interview_assistant.* TO 'interview'@'localhost';
FLUSH PRIVILEGES;
```

然后修改 `backend/.env` 中的连接地址：

```dotenv
MYSQL_URL=mysql+pymysql://interview:你的密码@127.0.0.1:3306/interview_assistant?charset=utf8mb4
```

如果密码包含 `@`、`:`、`/` 等字符，需要先进行 URL 编码。

### 执行数据库迁移

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
Pop-Location
```

## Agent 配置

在 `backend/.env` 中填写 DeepSeek 配置：

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
AGENT_MODEL_NAME=interview-assistant
```

请将 API Key 只保存在本地 `backend/.env` 中，不要写入代码或 `.env.example`。

客户端只访问本地 Agent 服务。服务端对外提供 OpenAI 兼容接口：

- `POST /v1/chat/completions`
- `GET /v1/models`

## 外部服务配置

### 飞书

先确认本机飞书 CLI 已完成用户登录和文档授权，再在 `backend/.env` 中配置：

```dotenv
FEISHU_InterviewDate_TOKEN=
FEISHU_Progress_TOKEN=
FEISHU_InterviewQuestion_TOKEN=
FEISHU_CLI_PATH=lark-cli
FEISHU_NODE_PATH=node
FEISHU_CLI_PROFILE=
```

三个链接分别对应：

- 笔试/面试日期多维表格；
- 投递进度文档中的电子表格；
- 个人面经或面经索引文档。

当前代码只读取面经文档中 `ZMY` 标题下的内容。其他使用者可以修改 `backend/app/integrations/feishu_sources.py` 中的 `OWNER`。

### 网易邮箱

在网易邮箱中开启 IMAP，生成客户端授权码，然后配置：

```dotenv
NETEASE_IMAP_HOST=imap.163.com
NETEASE_IMAP_PORT=993
NETEASE_EMAIL=
NETEASE_EMAIL_AUTH_CODE=
```

126 邮箱将 `NETEASE_IMAP_HOST` 改为 `imap.126.com`。这里填写的是客户端授权码，不是邮箱登录密码。

邮件正文只在本次扫描的内存中用于提取，不写入 MySQL 或 SQLite。成功处理后只保存邮件标识和处理结果。

### BOSS 直聘

双击 `start-boss-login.bat`，在打开的专用 Edge 窗口中手动登录并完成网站验证。看到岗位列表后返回终端按回车，程序会保存本地浏览器登录态。

随后进入客户端的“推荐岗位”页面，点击“重新匹配”。项目不会绕过网站验证，也不会自动投递岗位。

## 启动

双击根目录的 `start.bat`，或执行：

```powershell
.\start.bat
```

启动脚本会：

1. 检查项目虚拟环境；
2. 在本机 `127.0.0.1:8000` 启动 FastAPI；
3. 等待健康检查通过；
4. 打开 PySide6 客户端；
5. 客户端退出后，关闭由本次脚本启动的服务端。

服务端地址：

- 健康检查：<http://127.0.0.1:8000/api/health>
- OpenAPI 文档：<http://127.0.0.1:8000/docs>

## 接入检查

下面的命令只读检查飞书和网易邮箱，不修改飞书、不标记邮件已读，也不会调用付费模型：

```powershell
.\.venv\Scripts\python.exe -m scripts.check_integrations
```

额外检查 BOSS 公开页面：

```powershell
.\.venv\Scripts\python.exe -m scripts.check_integrations --boss
```

## 测试

后端测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -t . -v
```

前端测试：

```powershell
$env:PYTHONPATH = (Resolve-Path frontend).Path
.\.venv\Scripts\python.exe -m unittest discover -s frontend\tests -v
```

## 数据与安全

以下内容已由 `.gitignore` 排除，不应上传到 GitHub：

- `backend/.env` 和 API Key；
- 网易邮箱账号与授权码；
- 飞书私人文档链接；
- MySQL/SQLite 本地数据；
- BOSS 浏览器登录态、Cookie 和缓存；
- Python 虚拟环境、日志和缓存文件。

提交前可以运行：

```powershell
git status --short --ignored
```

请勿使用 `git add -f backend/.env` 绕过忽略规则。

## 设计文档

- [客户端设计](CLIENT_DESIGN.md)
- [服务端、Agent 与接口设计](SERVER_DESIGN.md)
- [后端运行说明](backend/README.md)
