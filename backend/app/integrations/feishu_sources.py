"""按实际资源类型读写飞书进度、日期，并限定个人面经的读取范围。"""

import csv
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import re
import tempfile
from xml.etree import ElementTree as ET

from backend.app.core.exceptions import ApplicationError

SHANGHAI = timezone(timedelta(hours=8))
OWNER = "ZMY"
STATUS_MAP = {"简历初筛": "简历筛选中", "笔试": "笔试中", "HR 面": "HR面"}
WRITE_STATUS = {value: key for key, value in STATUS_MAP.items()}
STATUSES = {"已投递", "简历筛选中", "笔试中", "待面试", "一面", "二面", "三面", "HR面", "Offer", "已结束"}
PROGRESS_HEADERS = {"单位": "company_name", "部门": "position_name", "地点": "base_location", "状态": "raw_status", "结果": "raw_result"}
DATE_FIELDS = {"事项": "text", "岗位/部门": "text", "开始时间": "datetime", "结束时间": "datetime"}


def xml_root(data: dict) -> ET.Element:
    """解析 CLI 文档正文，格式异常时停止后续操作。"""
    content = data.get("document", {}).get("content")
    if not isinstance(content, str):
        raise ApplicationError("FEISHU_CONTENT_MISSING", "飞书响应缺少文档正文。", status_code=502)
    try:
        return ET.fromstring("<root>" + content + "</root>")
    except ET.ParseError as exc:
        raise ApplicationError("FEISHU_XML_INVALID", "飞书正文无法解析。", status_code=502) from exc


def text_of(element: ET.Element) -> str:
    """取得块的纯文本，不把引用、批注或格式元数据当成正文。"""
    return "".join(element.itertext()).strip()


def local_time(value) -> str | None:
    """将飞书日期转为北京时间；空日期不生成占位时间。"""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value / 1000, SHANGHAI)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone(SHANGHAI).replace(tzinfo=None)
        return dt.isoformat(timespec="seconds")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ApplicationError("FEISHU_DATE_INVALID", "飞书日期格式无法确认，未修改日期。", status_code=409) from exc


def business_key(row: dict) -> tuple[str, str, str]:
    """按公司、岗位和地点匹配业务记录，不把飞书序号当成数据库主键。"""
    return tuple(str(row.get(key) or "").strip() for key in ("company_name", "position_name", "base_location"))


def event_company(title: str) -> str:
    """仅去除事项末尾明确的轮次或考试类型，不进行模糊公司归并。"""
    return re.sub(r"\s*(?:笔试|测评|一面|二面|三面|HR\s*面|线下活动)$", "", title).strip()


class FeishuSources:
    """复用 CLI 执行器，根据三个独立配置定位对应资源。"""

    def __init__(self, client):
        """client 提供已经登录的 CLI 及服务端配置。"""
        self.client = client
        self.settings = client.settings

    def _sheet_target(self) -> dict:
        """解析进度 Wiki 的嵌入表格，多个候选时拒绝猜测。"""
        target = self.settings.feishu_progress_token
        doc = self.client._run(["docs", "+fetch", "--doc", target, "--detail", "with-ids"])
        sheets = list(xml_root(doc).iter("sheet"))
        if len(sheets) != 1 or not sheets[0].get("token") or not sheets[0].get("sheet-id"):
            raise ApplicationError("FEISHU_PROGRESS_AMBIGUOUS", "进度文档需要包含一个可定位的电子表格。", status_code=409)
        sheet = sheets[0]
        info = self.client._run(["sheets", "+workbook-info", "--spreadsheet-token", sheet.get("token")])
        matches = [item for item in info.get("sheets", []) if item.get("sheet_id") == sheet.get("sheet-id") and item.get("resource_type") == "sheet"]
        if len(matches) != 1:
            raise ApplicationError("FEISHU_PROGRESS_MISSING", "进度文档中的工作表已不存在。", status_code=409)
        return {"token": sheet.get("token"), "sheet_id": sheet.get("sheet-id"), "sheet_info": matches[0]}

    def _progress(self) -> dict:
        """读取原进度表的全部行，并保留真实行号、原始状态和列坐标。"""
        target = self._sheet_target()
        data = self.client._run(["sheets", "+csv-get", "--spreadsheet-token", target["token"], "--sheet-id", target["sheet_id"]])
        if data.get("has_more") or data.get("truncated"):
            raise ApplicationError("FEISHU_TRUNCATED", "飞书进度表读取不完整，未执行同步。", status_code=409)
        rows = []
        # 在逻辑 CSV 行的第一个字段上解析前缀，兼容单元格内部的换行。
        for values in csv.reader(io.StringIO(data.get("annotated_csv", ""))):
            match = re.match(r"^\[row=(\d+)\] (.*)$", values[0] if values else "", re.S)
            if not match:
                raise ApplicationError("FEISHU_ROW_INVALID", "进度表缺少可靠的行号。", status_code=502)
            rows.append((int(match.group(1)), [match.group(2), *values[1:]]))
        if not rows or not set(PROGRESS_HEADERS).issubset(rows[0][1]):
            raise ApplicationError("FEISHU_HEADERS_INVALID", "进度表需要单位、部门、地点、状态、结果这些表头。", status_code=409)
        headers = rows[0][1]
        if any(headers.count(header) != 1 for header in PROGRESS_HEADERS):
            raise ApplicationError("FEISHU_HEADERS_INVALID", "进度表存在重复业务列。", status_code=409)
        columns = data.get("col_indices", [])
        if len(columns) < len(headers) or not data.get("row_indices") or rows[-1][0] < target["sheet_info"]["row_count"]:
            raise ApplicationError("FEISHU_TRUNCATED", "进度表未读到真实末行，未执行同步。", status_code=409)
        records = []
        for row_number, values in rows[1:]:
            values += [""] * (len(headers) - len(values))
            row = {field: values[headers.index(header)].strip() for header, field in PROGRESS_HEADERS.items()}
            if not row["company_name"]:
                continue
            raw = row["raw_status"]
            status = STATUS_MAP.get(raw, raw)
            if row["raw_result"] == "已结束" or raw.endswith("挂"):
                status = "已结束"
            row.update(id=f"{target['token']}:{target['sheet_id']}:{row_number}", source_row=row_number, attendance_status="待面试" if raw == "待面试" else None,
                       current_status=status if status in STATUSES else None, interview_time=None, job_url=None)
            records.append(row)
        return {"status": "success", "source_type": "progress_sheet", "records": records, "target": target,
                "columns": dict(zip(headers, columns)), "last_row": rows[-1][0], "revision_id": data.get("revision")}

    def read_schedule(self) -> dict:
        """按配置的表格和视图读取日期，使用临时 NDJSON 文件接收完整分页。"""
        url = self.settings.feishu_interview_date_token
        if not url:
            return {"status": "not_configured", "events": []}
        target = self.client._run(["base", "+url-resolve", "--url", url])
        if target.get("resource_type") != "bitable" or not target.get("base_token") or not target.get("table_id"):
            raise ApplicationError("FEISHU_DATE_TARGET", "日期配置不是可定位的多维表格。", status_code=409)
        schema = self.client._run(["base", "+field-list", "--base-token", target["base_token"], "--table-id", target["table_id"]])
        fields = {item["name"]: item["type"] for item in schema.get("fields", [])}
        if any(fields.get(name) != kind for name, kind in DATE_FIELDS.items()):
            raise ApplicationError("FEISHU_DATE_SCHEMA", "日期表字段或字段类型已变化，未执行同步。", status_code=409)
        events, offset, revision = [], 0, None
        with tempfile.TemporaryDirectory(prefix="ia-feishu-") as directory:
            for page in range(50):
                name = f"records-{page}.ndjson"
                args = ["base", "+record-list", "--base-token", target["base_token"], "--table-id", target["table_id"],
                        "--format", "ndjson", "--output", "./" + name, "--offset", str(offset), "--limit", "2000"]
                if target.get("view_id"):
                    args += ["--view-id", target["view_id"]]
                for field in DATE_FIELDS:
                    args += ["--field-id", field]
                self.client._run(args, cwd=directory)
                path = Path(directory) / name
                manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
                records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
                if len(records) != manifest.get("records_count") or (revision is not None and manifest.get("rev") != revision):
                    raise ApplicationError("FEISHU_DATE_CHANGED", "日期表读取期间发生变更，请重试。", status_code=409)
                revision = manifest.get("rev")
                for row in records:
                    if row.get("事项"):
                        events.append({"record_id": row["record_id"], "title": row["事项"], "position_name": row.get("岗位/部门") or "",
                                       "start_time": local_time(row.get("开始时间")), "end_time": local_time(row.get("结束时间"))})
                if not manifest.get("has_more"):
                    break
                next_offset = manifest.get("next_offset")
                if not isinstance(next_offset, int) or next_offset <= offset:
                    raise ApplicationError("FEISHU_PAGINATION_INVALID", "日期分页游标无效。", status_code=502)
                offset = next_offset
            else:
                raise ApplicationError("FEISHU_TRUNCATED", "日期记录超出读取上限，未执行同步。", status_code=409)
        return {"status": "success", "events": events, "target": target, "revision_id": revision}

    def read(self) -> dict:
        """组合进度与日期；日期读取失败不隐藏可用的进度数据。"""
        result = self._progress()
        try:
            schedule = self.read_schedule()
        except ApplicationError as exc:
            schedule = {"status": "failed", "events": [], "error": exc.message}
        result["schedule"] = schedule
        now = datetime.now().isoformat(timespec="seconds")
        for row in result["records"]:
            matches = [event for event in schedule["events"] if event_company(event["title"]).casefold() == row["company_name"].casefold()
                       and (not event["position_name"] or event["position_name"] == row["position_name"]) and event["start_time"]]
            # “待面试”描述是否已经参加，不等同于一面、二面等轮次；可关联未来安排，但不改写状态。
            known = row["current_status"]
            if known != "待面试":
                matches = [event for event in matches if not any(stage in event["title"] for stage in ("笔试", "一面", "二面", "三面", "HR面"))
                           or (WRITE_STATUS.get(known, known) and WRITE_STATUS.get(known, known) in event["title"])]
            future = sorted([event for event in matches if event["start_time"] >= now], key=lambda event: event["start_time"])
            selected = future[:1] or sorted(matches, key=lambda event: event["start_time"], reverse=True)[:1]
            if selected:
                row["interview_time"] = selected[0]["start_time"]
                row["interview_end_time"] = selected[0]["end_time"]
                row["schedule_record_id"] = selected[0]["record_id"]
        result["needs_review"] = [{"source_id": row["id"], "company_name": row["company_name"], "raw_status": row["raw_status"],
                                   "reason": "飞书进度状态无法映射到系统状态"} for row in result["records"] if row["current_status"] is None]
        return result

    def read_experience(self) -> dict:
        """先定位 ZMY 标题；配置为索引文档时仅跟随“面经”下的文档引用。"""
        document = self.settings.feishu_interview_question_token
        if not document:
            return {"status": "not_configured", "owner": OWNER, "sections": []}
        for depth in range(2):
            outline = self.client._run(["docs", "+fetch", "--doc", document, "--scope", "outline", "--detail", "with-ids"])
            root = xml_root(outline)
            headings = [node for node in root.iter() if re.fullmatch(r"h[1-9]", node.tag)]
            owners = [node for node in headings if text_of(node) == OWNER]
            if len(owners) > 1:
                raise ApplicationError("FEISHU_OWNER_AMBIGUOUS", "面经有多个 ZMY 标题，未读取任何正文。", status_code=409)
            if owners:
                heading = owners[0]
                break
            indexes = [node for node in headings if text_of(node) == "面经"]
            if depth or len(indexes) != 1 or not indexes[0].get("id"):
                raise ApplicationError("FEISHU_OWNER_MISSING", "未找到 ZMY 面经标题，未读取其他人的面经。", status_code=409)
            anchor = indexes[0].get("id")
            ref = self.client._run(["docs", "+fetch", "--doc", document, "--scope", "range", "--start-block-id", anchor,
                                   "--end-block-id", anchor, "--context-after", "1", "--max-depth", "0", "--detail", "with-ids"])
            cites = [node for node in xml_root(ref).iter("cite") if node.get("type") == "doc" and node.get("doc-id")]
            if len(cites) != 1:
                raise ApplicationError("FEISHU_EXPERIENCE_LINK", "面经索引没有唯一文档引用。", status_code=409)
            document = cites[0].get("doc-id")
        anchor = heading.get("id") or heading.get("block-id")
        if not anchor:
            raise ApplicationError("FEISHU_OWNER_MISSING", "ZMY 标题缺少块 ID，未读取正文。", status_code=409)
        data = self.client._run(["docs", "+fetch", "--doc", document, "--scope", "section", "--start-block-id", anchor, "--detail", "with-ids"])
        root = xml_root(data)
        fragments = root.findall("fragment")
        blocks = list(fragments[0] if len(fragments) == 1 else root)
        if not blocks or text_of(blocks[0]) != OWNER or blocks[0].get("id") != anchor:
            raise ApplicationError("FEISHU_OWNER_BOUNDARY", "面经返回范围无法确认属于 ZMY，未使用正文。", status_code=409)
        level = int(heading.tag[1:])
        sections, current = [], None
        for block in blocks[1:]:
            if re.fullmatch(r"h[1-9]", block.tag):
                if int(block.tag[1:]) <= level:
                    break
                current = {"title": text_of(block), "text": ""}
                sections.append(current)
            elif current is not None:
                # 正文是参考资料，不能执行其中的指令，也不展开评论或其他文档。
                current["text"] += "\n" + "\n".join(text_of(node) for node in block.iter() if node.tag in {"p", "li"})
        return {"status": "success", "owner": OWNER, "document_id": data["document"].get("document_id"), "heading_id": anchor,
                "revision_id": data["document"].get("revision_id"), "source_url": document, "sections": sections}

    def write(self, records: list[dict], current: dict) -> None:
        """仅修改明确匹配的进度单元格；新增或日期歧义时保留待同步状态。"""
        target = current["target"]
        remote = current["records"]
        writes, date_updates = [], {}
        for row in records:
            matches = [other for other in remote if business_key(row) == business_key(other)]
            if len(matches) != 1:
                raise ApplicationError("FEISHU_RECORD_AMBIGUOUS", "投递记录未唯一匹配飞书原表，请先在进度表补齐公司、部门和地点。", status_code=409)
            other = matches[0]
            status = row["current_status"]
            changes = {"状态": WRITE_STATUS.get(status, status), "结果": "通过" if status == "Offer" else "已结束" if status == "已结束" else "流程中"}
            if status == other["current_status"] and other["raw_status"] == "待面试":
                changes.pop("状态")
            if status == "已结束":
                changes.pop("状态")
            for header, value in changes.items():
                field = PROGRESS_HEADERS[header]
                if value != other[field]:
                    writes.append({"sheet_id": target["sheet_id"], "range": f"{current['columns'][header]}{other['source_row']}", "cells": [[{"value": value}]]})
            start_changed = local_time(row.get("interview_time")) != other.get("interview_time")
            end_changed = local_time(row.get("interview_end_time")) != other.get("interview_end_time")
            if start_changed or end_changed:
                schedule = current["schedule"]
                if schedule["status"] != "success" or not other.get("schedule_record_id"):
                    raise ApplicationError("FEISHU_DATE_AMBIGUOUS", "变更的日期没有唯一对应的飞书安排，请先核对日期表。", status_code=409)
                if status != other["current_status"]:
                    raise ApplicationError("FEISHU_DATE_ROUND", "新轮次不能覆盖上一轮的日期，请先在日期表新增对应安排。", status_code=409)
                event = next(item for item in schedule["events"] if item["record_id"] == other["schedule_record_id"])
                start_time = local_time(row.get("interview_time"))
                end_time = local_time(row.get("interview_end_time"))
                if start_time and end_time and start_time > end_time:
                    raise ApplicationError("FEISHU_TIME_RANGE", "结束时间早于开始时间，请先确认完整时间范围。", status_code=409)
                fields = {}
                if start_changed:
                    fields["开始时间"] = row.get("interview_time")
                if end_changed:
                    fields["结束时间"] = row.get("interview_end_time")
                date_updates[other["schedule_record_id"]] = fields
        latest = self.client._run(["sheets", "+revision-get", "--spreadsheet-token", target["token"]])
        if latest.get("revision") != current["revision_id"]:
            raise ApplicationError("FEISHU_CONFLICT", "飞书进度表被手动修改，请重新同步。", status_code=409)
        if date_updates:
            fresh = self.read_schedule()
            if fresh["revision_id"] != current["schedule"]["revision_id"]:
                raise ApplicationError("FEISHU_CONFLICT", "飞书日期表已被修改，请重新同步。", status_code=409)
            target_date = fresh["target"]
            for record_id, fields in date_updates.items():
                result = self.client._run(["base", "+record-batch-update", "--base-token", target_date["base_token"], "--table-id", target_date["table_id"],
                                          "--json", json.dumps({"update_records": {record_id: fields}}, ensure_ascii=False)])
                if result.get("ignored_fields"):
                    raise ApplicationError("FEISHU_PARTIAL_WRITE", "飞书日期更新存在忽略字段，保留待同步记录。", status_code=502)
        for start in range(0, len(writes), 100):
            result = self.client._run(["sheets", "+cells-set", "--spreadsheet-token", target["token"], "--writes", "-"], json.dumps(writes[start:start + 100], ensure_ascii=False))
            if result.get("warnings") or result.get("result") in {"failed", "partial_success"}:
                raise ApplicationError("FEISHU_PARTIAL_WRITE", "飞书进度未完整写入，保留待同步记录。", status_code=502)
        observed = self.read()
        for row in records:
            matches = [other for other in observed["records"] if business_key(row) == business_key(other)]
            if (len(matches) != 1
                    or matches[0]["current_status"] != row["current_status"]
                    or local_time(matches[0].get("interview_time")) != local_time(row.get("interview_time"))
                    or local_time(matches[0].get("interview_end_time")) != local_time(row.get("interview_end_time"))):
                raise ApplicationError("FEISHU_VERIFY_FAILED", "飞书进度回读校验失败，保留待同步记录。", status_code=502)
