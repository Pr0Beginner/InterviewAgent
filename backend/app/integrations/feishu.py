"""读取飞书文档并解析本应用管理的汇总表，写入仅限该表。"""

import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
from threading import Lock
from xml.etree import ElementTree as ET
from html import escape

from backend.app.core.config import get_settings
from backend.app.core.exceptions import ApplicationError

SYNC_LOCK = Lock()
logger = logging.getLogger(__name__)
HEADERS = ["IA记录ID", "公司", "岗位", "Base", "状态", "面试时间", "岗位链接", "更新时间"]
FIELDS = ["id", "company_name", "position_name", "base_location", "current_status", "interview_time", "job_url", "updated_at"]


def _safe_cli_error(payload: dict, returncode: int, arguments: list[str]) -> dict:
    """提取可展示的 CLI 错误字段，不返回令牌、文档内容或完整命令参数。"""
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    operation = " ".join(arguments[:2]) if arguments else "unknown"
    details = {
        "operation": operation,
        "exit_code": returncode,
        "identity": payload.get("identity"),
        "type": error.get("type"),
        "subtype": error.get("subtype"),
        "code": error.get("code"),
        "message": str(error.get("message") or "CLI 未返回错误说明。")[:500],
    }
    missing_scopes = error.get("missing_scopes")
    if isinstance(missing_scopes, list):
        details["missing_scopes"] = [str(scope)[:200] for scope in missing_scopes[:20]]
    hint = error.get("hint")
    if isinstance(hint, str):
        details["hint"] = hint[:500]
    return {key: value for key, value in details.items() if value is not None}


class FeishuClient:
    """飞书 CLI 适配器；参数不经过 Shell，XML 内容通过标准输入传递。"""

    def __init__(self, settings=None):
        """测试时使用显式传入的配置，运行时使用缓存的服务端配置。"""
        self.settings = settings or get_settings()

    def _run(self, arguments: list[str], content: str | None = None, cwd: str | None = None) -> dict:
        """执行固定的 CLI 参数；内容通过标准输入传递，不进行 Shell 字符串插值。"""
        executable = shutil.which(self.settings.feishu_cli_path)
        if not executable:
            raise ApplicationError("FEISHU_CLI_MISSING", "未找到 lark-cli，请安装并登录。", status_code=503)
        command = [executable]
        if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".ps1"}:
            script = Path(executable).parent / "node_modules/@larksuite/cli/scripts/run.js"
            node = shutil.which(self.settings.feishu_node_path)
            if not script.is_file() or not node:
                raise ApplicationError(
                    "FEISHU_CLI_PATH",
                    "飞书 CLI 或 Node.js 路径无效，请检查 FEISHU_CLI_PATH 和 FEISHU_NODE_PATH。",
                    status_code=503,
                )
            command = [node, str(script)]
        environment = os.environ.copy()
        environment["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
        environment["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
        profile_arguments = (
            ["--profile", self.settings.feishu_cli_profile]
            if self.settings.feishu_cli_profile else []
        )
        try:
            result = subprocess.run(command + profile_arguments + arguments + ["--as", "user"], input=content,
                text=True, encoding="utf-8", capture_output=True, timeout=40,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                cwd=cwd, env=environment)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ApplicationError("FEISHU_UNAVAILABLE", "飞书 CLI 执行失败或超时。", status_code=503) from exc
        if result.returncode == 10:
            raise ApplicationError("FEISHU_CONFIRMATION_REQUIRED", "飞书操作需要 CLI 人工确认，请完成配置后重试。", status_code=409)
        try:
            payload = json.loads(result.stdout if result.returncode == 0 else result.stderr)
        except ValueError as exc:
            raise ApplicationError("FEISHU_INVALID_RESPONSE", "飞书 CLI 返回格式错误。", status_code=502) from exc
        # 多维表格 NDJSON 导出的 stdout 是清单本身，不使用普通 JSON 成功信封。
        if not result.returncode and arguments[:2] == ["base", "+record-list"] and "ndjson" in arguments and payload.get("manifest_version") == "v1" and payload.get("format") == "ndjson":
            return payload
        if result.returncode or payload.get("ok") is not True:
            details = _safe_cli_error(payload, result.returncode, arguments)
            logger.warning("feishu_cli_failed details=%s", json.dumps(details, ensure_ascii=False))
            message = details.get("message") or "飞书 CLI 请求失败。"
            raise ApplicationError(
                "FEISHU_REQUEST_FAILED",
                f"飞书 CLI 请求失败：{message}",
                status_code=502,
                details=details,
            )
        if not isinstance(payload.get("data"), dict):
            raise ApplicationError("FEISHU_INVALID_RESPONSE", "飞书 CLI 响应缺少 data 对象。", status_code=502)
        return payload["data"]
    def read(self) -> dict:
        """获取当前文档的 XML 并解析应用汇总表，不执行修改。"""
        if self.settings.feishu_progress_token:
            from backend.app.integrations.feishu_sources import FeishuSources
            return FeishuSources(self).read()
        document = self.settings.feishu_document_token
        if not document:
            return {"status": "not_configured", "records": []}
        data = self._run(["docs", "+fetch", "--doc", document, "--detail", "full"])
        doc = data.get("document", {})
        content = doc.get("content")
        if not isinstance(content, str):
            raise ApplicationError("FEISHU_INVALID_RESPONSE", "飞书响应缺少文档正文，未修改文档。", status_code=502)
        try:
            root = ET.fromstring("<root>" + content + "</root>")
        except ET.ParseError as exc:
            raise ApplicationError("FEISHU_XML_INVALID", "飞书内容无法解析，未修改文档。", status_code=502) from exc
        tables = [table for table in root.iter("table") if any("".join(cell.itertext()) == HEADERS[0] for cell in table.iter("th"))]
        if len(tables) > 1:
            raise ApplicationError("FEISHU_AMBIGUOUS_TABLE", "文档中有多个 IA 汇总表，请保留一个。", status_code=409)
        records = []
        block_id = None
        if tables:
            table = tables[0]
            block_id = table.get("block-id") or table.get("id")
            if not block_id:
                raise ApplicationError("FEISHU_BLOCK_ID_MISSING", "汇总表缺少块 ID，未修改文档。", status_code=409)
            for row in table.iter("tr"):
                cells = row.findall("td")
                if not cells:
                    continue
                values = ["".join(cell.itertext()).strip() for cell in cells]
                if len(values) != len(FIELDS) or not values[0].isdigit():
                    raise ApplicationError("FEISHU_TABLE_INVALID", "IA 汇总表存在格式错误，请先修正。", status_code=409)
                record = dict(zip(FIELDS, values))
                record["id"] = int(record["id"])
                records.append(record)
        return {"status": "success", "records": records, "block_id": block_id, "revision_id": doc.get("revision_id", -1)}

    def write(self, records: list[dict], current: dict) -> None:
        """替换刚读取到的应用汇总表；表不存在时追加，写入后进行校验。
        
        参数:
            records: 从 MySQL 读取、可序列化为 JSON 的投递记录。
            current: 最新读取结果，包含块 ID 和文档版本号。
        """
        if current.get("source_type") == "progress_sheet":
            from backend.app.integrations.feishu_sources import FeishuSources
            return FeishuSources(self).write(records, current)
        if current["status"] != "success":
            raise ApplicationError("FEISHU_NOT_CONFIGURED", "请配置 FEISHU_DOCUMENT_TOKEN。", status_code=503)
        if not isinstance(current.get("revision_id"), int) or current["revision_id"] < 0:
            raise ApplicationError("FEISHU_REVISION_MISSING", "无法取得文档版本，未执行写入。", status_code=409)
        rows = "".join("<tr>" + "".join(f"<td><p>{escape(str(record.get(field) or ''))}</p></td>" for field in FIELDS) + "</tr>" for record in records)
        table = "<table><thead><tr>" + "".join(f"<th><p>{header}</p></th>" for header in HEADERS) + "</tr></thead><tbody>" + rows + "</tbody></table>"
        args = ["docs", "+update", "--doc", self.settings.feishu_document_token,
                "--command", "block_replace" if current["block_id"] else "append",
                "--content", "-", "--revision-id", str(current["revision_id"])]
        if current["block_id"]:
            args.extend(["--block-id", current["block_id"]])
        result = self._run(args, table)
        if result.get("result") != "success" or result.get("warnings"):
            raise ApplicationError("FEISHU_PARTIAL_WRITE", "飞书未完整写入，保留待同步记录。", status_code=502)
        observed = self.read()["records"]
        normalize = lambda rows: [{key: str(row.get(key) or "") for key in FIELDS} for row in rows]
        if normalize(observed) != normalize(records):
            raise ApplicationError("FEISHU_VERIFY_FAILED", "飞书写入校验失败，保留待同步记录。", status_code=502)

    def read_experience(self) -> dict:
        """只读取配置面经中 ZMY 的正文，不读取或写入其他人的面经。"""
        from backend.app.integrations.feishu_sources import FeishuSources
        return FeishuSources(self).read_experience()
