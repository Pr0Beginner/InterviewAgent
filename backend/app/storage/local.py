"""使用 Markdown 和 JSON 保存个人项目的小规模业务数据。"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.exceptions import ApplicationError
from backend.app.models.enums import INTERVIEW_STATUS_VALUES


表头 = ["ID", "公司", "岗位", "Base", "状态", "开始时间", "结束时间", "岗位链接", "创建时间", "更新时间"]
文件说明 = """# 投递记录

> 这是 Interview Assistant 的本地数据文件。可以直接查看；程序运行时请通过客户端修改，避免同时写入。

"""
_锁集合: dict[str, RLock] = {}
_锁集合保护 = RLock()


def _文件锁(path: Path) -> RLock:
    """让同一进程中指向同一文件的服务实例共用写锁。"""
    key = str(path.resolve())
    with _锁集合保护:
        return _锁集合.setdefault(key, RLock())


def _时间文本(value: datetime | str | None) -> str:
    """将时间统一保存为便于阅读和排序的本地格式。"""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _解析时间(value: str | None) -> datetime | None:
    """读取 Markdown 中的可选时间。"""
    if not value:
        return None
    return datetime.fromisoformat(value)


def _编码单元格(value: Any) -> str:
    """转义会破坏 Markdown 表格结构的字符。"""
    if value is None:
        return ""
    return str(value).replace("&", "&amp;").replace("|", "&#124;").replace("\r\n", "<br>").replace("\n", "<br>")


def _解码单元格(value: str) -> str:
    """还原 Markdown 表格单元格中的转义内容。"""
    return value.strip().replace("<br>", "\n").replace("&#124;", "|").replace("&amp;", "&")


@dataclass(slots=True)
class LocalInterview:
    """投递表格的一行本地记录。"""

    id: int
    company_name: str
    position_name: str
    base_location: str
    current_status: str
    interview_time: datetime | None = None
    interview_end_time: datetime | None = None
    job_url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class LocalInterviewPage:
    """本地筛选和分页结果。"""

    items: list[LocalInterview]
    total: int
    summary_total: int
    status_counts: dict[str, int]


class MarkdownInterviewStore:
    """原子读写本地 Markdown 投递表。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or get_settings().interviews_file_path)
        self.lock = _文件锁(self.path)
        self._ensure_file()

    def _ensure_file(self) -> None:
        """首次运行时创建只有表头的本地文件。"""
        with self.lock:
            if not self.path.exists():
                self._write([])

    def all(self) -> list[LocalInterview]:
        """读取全部记录，并返回与文件内容隔离的对象列表。"""
        with self.lock:
            return self._read()

    def list_page(
        self,
        *,
        company_name: str | None,
        position_name: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> LocalInterviewPage:
        """按公司、岗位和状态筛选，并按开始时间降序分页。"""
        records = self.all()
        base = [
            row
            for row in records
            if (not company_name or company_name.casefold() in row.company_name.casefold())
            and (not position_name or position_name.casefold() in row.position_name.casefold())
        ]
        counts = {value: 0 for value in INTERVIEW_STATUS_VALUES}
        for row in base:
            counts[row.current_status] = counts.get(row.current_status, 0) + 1
        filtered = [row for row in base if not status or row.current_status == status]
        filtered.sort(
            key=lambda row: (row.interview_time is not None, row.interview_time or datetime.min, row.id),
            reverse=True,
        )
        start = (page - 1) * page_size
        return LocalInterviewPage(
            items=filtered[start : start + page_size],
            total=len(filtered),
            summary_total=len(base),
            status_counts=counts,
        )

    def get(self, interview_id: int) -> LocalInterview | None:
        """按稳定 ID 读取单条记录。"""
        return next((row for row in self.all() if row.id == interview_id), None)

    def create(self, values: dict[str, Any]) -> LocalInterview:
        """创建不重复的投递记录并分配下一个 ID。"""
        with self.lock:
            records = self._read()
            duplicate = any(
                row.company_name == values["company_name"]
                and row.position_name == values["position_name"]
                and row.base_location == values["base_location"]
                for row in records
            )
            if duplicate:
                raise ApplicationError("APPLICATION_EXISTS", "该公司、岗位与 Base 已有记录，请先查询。", status_code=409)
            now = datetime.now()
            row = LocalInterview(
                id=max((item.id for item in records), default=0) + 1,
                created_at=now,
                updated_at=now,
                **values,
            )
            records.append(row)
            self._write(records)
            return row

    def update(
        self,
        interview_id: int,
        values: dict[str, Any],
        expected_status: str | None = None,
    ) -> tuple[LocalInterview, str]:
        """原子更新指定字段，并可校验调用方读取到的原状态。"""
        with self.lock:
            records = self._read()
            row = next((item for item in records if item.id == interview_id), None)
            if row is None:
                raise ApplicationError("INTERVIEW_NOT_FOUND", "投递记录不存在。", status_code=404)
            if expected_status is not None and row.current_status != expected_status:
                raise ApplicationError("STATUS_CONFLICT", "记录已被修改，请重新查询后操作。", status_code=409)
            previous_status = row.current_status
            for field, value in values.items():
                if hasattr(row, field):
                    setattr(row, field, value)
            row.updated_at = datetime.now()
            self._validate_time(row)
            self._write(records)
            return row, previous_status

    def replace_all(self, records: list[dict[str, Any] | LocalInterview]) -> None:
        """迁移时用一批完整记录替换本地文件。"""
        with self.lock:
            normalized = [item if isinstance(item, LocalInterview) else LocalInterview(**item) for item in records]
            for row in normalized:
                self._validate_time(row)
            self._write(normalized)

    @staticmethod
    def _validate_time(row: LocalInterview) -> None:
        if row.interview_end_time is not None and row.interview_time is None:
            raise ApplicationError("INTERVIEW_TIME_RANGE", "设置结束时间前必须先设置开始时间。", status_code=422)
        if row.interview_time and row.interview_end_time and row.interview_end_time < row.interview_time:
            raise ApplicationError("INTERVIEW_TIME_RANGE", "结束时间不能早于开始时间。", status_code=422)

    def _read(self) -> list[LocalInterview]:
        """解析固定列的 Markdown 表格。"""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ApplicationError("LOCAL_DATA_READ_FAILED", "本地投递文件读取失败。", status_code=500) from exc
        table_rows = [line for line in lines if line.startswith("|")]
        if len(table_rows) < 2:
            return []
        headers = [_解码单元格(cell) for cell in table_rows[0].strip("|").split("|")]
        if headers != 表头:
            raise ApplicationError("LOCAL_DATA_INVALID", "本地投递文件表头已被修改，无法安全读取。", status_code=500)
        records: list[LocalInterview] = []
        for line in table_rows[2:]:
            cells = [_解码单元格(cell) for cell in line.strip("|").split("|")]
            if len(cells) != len(表头):
                raise ApplicationError("LOCAL_DATA_INVALID", "本地投递文件存在列数不正确的记录。", status_code=500)
            records.append(LocalInterview(
                id=int(cells[0]), company_name=cells[1], position_name=cells[2],
                base_location=cells[3], current_status=cells[4],
                interview_time=_解析时间(cells[5]), interview_end_time=_解析时间(cells[6]),
                job_url=cells[7] or None, created_at=_解析时间(cells[8]), updated_at=_解析时间(cells[9]),
            ))
        return records

    def _write(self, records: list[LocalInterview]) -> None:
        """先写临时文件再替换，避免中途退出破坏原文件。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [文件说明.rstrip(), "", "| " + " | ".join(表头) + " |", "| " + " | ".join(["---"] * len(表头)) + " |"]
        for row in sorted(records, key=lambda item: item.id):
            values = [
                row.id, row.company_name, row.position_name, row.base_location, row.current_status,
                _时间文本(row.interview_time), _时间文本(row.interview_end_time), row.job_url or "",
                _时间文本(row.created_at), _时间文本(row.updated_at),
            ]
            lines.append("| " + " | ".join(_编码单元格(value) for value in values) + " |")
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ApplicationError("LOCAL_DATA_WRITE_FAILED", "本地投递文件保存失败。", status_code=500) from exc


class LocalStateStore:
    """保存邮件去重、任务、岗位缓存和模拟面试会话的本地 JSON。"""

    SECTIONS = (
        "email_receipts",
        "email_candidates",
        "tasks",
        "job_searches",
        "mock_sessions",
        "resumes",
        "operations",
    )

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or get_settings().local_state_path)
        self.lock = _文件锁(self.path)
        self._ensure_file()

    def _ensure_file(self) -> None:
        with self.lock:
            if not self.path.exists():
                self._write({name: {} for name in self.SECTIONS})

    def get(self, section: str, key: str) -> dict[str, Any] | None:
        with self.lock:
            value = self._read()[section].get(key)
            return deepcopy(value) if value is not None else None

    def values(self, section: str) -> list[dict[str, Any]]:
        with self.lock:
            return deepcopy(list(self._read()[section].values()))

    def put(self, section: str, key: str, value: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            data = self._read()
            data[section][key] = deepcopy(value)
            self._write(data)
            return deepcopy(value)

    def delete(self, section: str, key: str) -> None:
        with self.lock:
            data = self._read()
            data[section].pop(key, None)
            self._write(data)

    def update_if_version(
        self,
        section: str,
        key: str,
        expected_version: int,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        """以版本号避免同一模拟面试被并发覆盖。"""
        with self.lock:
            data = self._read()
            current = data[section].get(key)
            if current is None:
                raise ApplicationError("SESSION_NOT_FOUND", "模拟面试不存在。", status_code=404)
            if current.get("version") != expected_version:
                raise ApplicationError("SESSION_CONFLICT", "面试会话已被其他请求更新，请刷新。", status_code=409)
            current.update(deepcopy(changes), version=expected_version + 1)
            self._write(data)
            return deepcopy(current)

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ApplicationError("LOCAL_STATE_READ_FAILED", "本地运行状态文件读取失败。", status_code=500) from exc
        for section in self.SECTIONS:
            if not isinstance(data.get(section), dict):
                data[section] = {}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ApplicationError("LOCAL_STATE_WRITE_FAILED", "本地运行状态保存失败。", status_code=500) from exc
