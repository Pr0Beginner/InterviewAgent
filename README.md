# Interview Assistant

项目采用前后端分目录结构：

- `frontend/`：PySide6 桌面客户端和前端测试
- `backend/`：FastAPI 服务端、数据库基础设施、迁移和后端测试

## 一键启动

双击项目根目录中的 `start.bat`，或在终端运行：

```powershell
.\start.bat
```

首次运行前安装依赖：

```powershell
cd D:\projects\InterviewAssistant
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.bat
```

三个页面均调用真实服务端接口，Mock 仅用于测试。右侧 Agent 使用 OpenAI 兼容协议接入 DeepSeek，支持查询、新增和更新投递记录，以及调用岗位推荐、模拟面试和邮件扫描工具。

使用 Agent 前，在 `backend/.env` 的 `DEEPSEEK_API_KEY` 中填写密钥，确认 `DEEPSEEK_MODEL` 后重启服务端。客户端支持流式显示、停止生成、按 Tab 隔离对话历史；接口详情见 [服务端设计](SERVER_DESIGN.md)。

外部功能配置：

- 飞书：在 `backend/.env` 填写 `FEISHU_InterviewDate_TOKEN`、`FEISHU_Progress_TOKEN`、`FEISHU_InterviewQuestion_TOKEN`；分别用于日期、进度和个人面经，复用本机 CLI 登录态。
- 网易邮箱：开启 IMAP，在 `backend/.env` 填写 `NETEASE_EMAIL` 和 `NETEASE_EMAIL_AUTH_CODE`（邮箱授权码，不是登录密码）；126 邮箱同时修改 `NETEASE_IMAP_HOST`。
- BOSS：双击 `start-boss-login.bat`，在专用 Edge 窗口登录并完成验证，看到岗位列表后回到终端按回车。随后在推荐岗位页点击“重新匹配”。不会自动投递。

飞书按原表结构合并进度和日期，只定点修改唯一匹配的待同步记录，人工冲突不覆盖。“已投递”表示尚未收到笔试或面试邀请；“待面试”表示已收到面试邀请但尚未参加，二者都是正常状态。个人面经只读取 `ZMY` 部分。邮箱不保存正文，成功处理后记录标识并标记已读。模拟面试会话和总结存入数据库，可点击“恢复上次”。

只读接入检查：`.venv\Scripts\python.exe -m scripts.check_integrations --boss`。不写飞书、不标邮件已读，不调用付费模型；BOSS 探测不使用用户登录 Cookie。

`start.bat` 会检测本地后端；后端未运行时会在隐藏进程中启动，再打开客户端。客户端关闭后，一键脚本启动的后端也会结束；若后端原本已经运行，脚本会复用且不会关闭它。配置修改后需重启后端；邮件扫描期间关闭应用会中断任务，重新扫描会跳过已处理邮件。

服务端健康检查：`http://127.0.0.1:8000/api/health`

OpenAPI 文档：`http://127.0.0.1:8000/docs`
