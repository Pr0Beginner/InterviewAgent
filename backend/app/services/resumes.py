"""解析上传的简历，并将纯文本安全地保存在本地。"""

from __future__ import annotations

import os
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from docx import Document
from pypdf import PdfReader

from backend.app.core.config import get_settings
from backend.app.core.exceptions import ApplicationError
from backend.app.storage.local import LocalStateStore


class ResumeService:
    """负责简历格式校验、文本提取、元数据和文本文件持久化。"""

    MAX_BYTES = 10 * 1024 * 1024
    MAX_CHARACTERS = 120_000
    MODEL_CHARACTERS = 60_000
    ALLOWED_SUFFIXES = {".pdf", ".docx"}
    _ID_PATTERN = re.compile(r"^resume-[a-f0-9]{32}$")

    def __init__(self, storage_path: str | Path | None = None, state_store=None) -> None:
        settings = get_settings()
        self.storage_path = Path(storage_path or settings.resume_storage_path)
        self.state_store = state_store or LocalStateStore()

    def save(self, filename: str | None, data: bytes) -> dict:
        """解析一份 PDF/DOCX 简历并原子保存其纯文本。"""
        safe_name = Path(filename or "resume").name
        suffix = Path(safe_name).suffix.lower()
        if suffix not in self.ALLOWED_SUFFIXES:
            raise ApplicationError(
                "UNSUPPORTED_RESUME_FORMAT",
                "仅支持 PDF 或 DOCX 格式的简历；旧版 DOC 请先另存为 DOCX。",
                status_code=415,
            )
        if not data:
            raise ApplicationError("EMPTY_RESUME", "简历文件为空。")
        if len(data) > self.MAX_BYTES:
            raise ApplicationError("RESUME_TOO_LARGE", "简历文件不能超过 10 MB。", status_code=413)

        text = self._parse_pdf(data) if suffix == ".pdf" else self._parse_docx(data)
        text = self._normalize(text)
        if len(text) < 20:
            raise ApplicationError(
                "RESUME_TEXT_NOT_FOUND",
                "没有从简历中读取到足够文本；扫描版 PDF 请先进行 OCR。",
            )
        text = text[: self.MAX_CHARACTERS]
        resume_id = "resume-" + uuid4().hex
        created_at = datetime.now().isoformat()
        record = {
            "id": resume_id,
            "file_name": safe_name,
            "format": suffix.removeprefix("."),
            "character_count": len(text),
            "created_at": created_at,
        }
        self.storage_path.mkdir(parents=True, exist_ok=True)
        target = self.storage_path / f"{resume_id}.txt"
        temporary = target.with_suffix(".txt.tmp")
        try:
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise ApplicationError(
                "RESUME_SAVE_FAILED", "简历文本保存失败，请检查本地目录权限。", status_code=500
            ) from exc
        try:
            self.state_store.put("resumes", resume_id, record)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return record

    def get(self, resume_id: str) -> dict:
        """返回已保存的简历元数据，不暴露本地文件路径。"""
        if not self._ID_PATTERN.fullmatch(resume_id):
            raise ApplicationError("RESUME_NOT_FOUND", "简历不存在，请重新上传。", status_code=404)
        record = self.state_store.get("resumes", resume_id)
        if record is None or not (self.storage_path / f"{resume_id}.txt").is_file():
            raise ApplicationError("RESUME_NOT_FOUND", "简历不存在，请重新上传。", status_code=404)
        return record

    def model_context(self, resume_id: str) -> dict:
        """返回供面试模型分析的简历文本，并限制提示词体积。"""
        record = self.get(resume_id)
        try:
            text = (self.storage_path / f"{resume_id}.txt").read_text(encoding="utf-8")
        except OSError as exc:
            raise ApplicationError("RESUME_READ_FAILED", "简历文本读取失败。", status_code=500) from exc
        return {
            "file_name": record["file_name"],
            "text": text[: self.MODEL_CHARACTERS],
            "truncated": len(text) > self.MODEL_CHARACTERS,
        }

    @staticmethod
    def _parse_pdf(data: bytes) -> str:
        try:
            reader = PdfReader(BytesIO(data), strict=False)
            if reader.is_encrypted and reader.decrypt("") == 0:
                raise ApplicationError("ENCRYPTED_RESUME", "无法解析加密的 PDF 简历。")
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError("INVALID_RESUME", "PDF 简历无法解析，请检查文件是否损坏。") from exc

    @staticmethod
    def _parse_docx(data: bytes) -> str:
        try:
            document = Document(BytesIO(data))
            blocks = [paragraph.text for paragraph in document.paragraphs]
            for table in document.tables:
                blocks.extend("\t".join(cell.text for cell in row.cells) for row in table.rows)
            return "\n".join(blocks)
        except Exception as exc:
            raise ApplicationError("INVALID_RESUME", "Word 简历无法解析，请检查文件是否损坏。") from exc

    @staticmethod
    def _normalize(text: str) -> str:
        lines = []
        for line in text.replace("\x00", "").splitlines():
            normalized = " ".join(line.split())
            if normalized:
                lines.append(normalized)
        return "\n".join(lines)
