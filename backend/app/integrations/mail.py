"""网易 IMAP 适配器：使用 PEEK 读取邮件，仅在成功处理后设置已读标记 Seen。"""

from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from hashlib import sha256
import imaplib
import re
import ssl

from bs4 import BeautifulSoup

from backend.app.core.config import get_settings
from backend.app.core.exceptions import ApplicationError


class NeteaseMailbox:
    """按账户建立邮箱连接，不持久化邮件正文或授权码。"""

    def __init__(self, settings=None):
        """从服务端配置读取邮箱服务器、账户和授权码。"""
        self.settings = settings or get_settings()

    def ensure_configured(self):
        """缺少邮箱账户或 IMAP 授权码时拒绝扫描。"""
        if not self.settings.netease_email or not self.settings.netease_email_auth_code:
            raise ApplicationError("EMAIL_NOT_CONFIGURED", "请配置 NETEASE_EMAIL 和 NETEASE_EMAIL_AUTH_CODE。", status_code=503)

    @contextmanager
    def connect(self, readonly: bool = False):
        """打开收件箱；readonly 为真时使用只读模式，不能修改邮件标记。"""
        self.ensure_configured()
        client = None
        try:
            client = imaplib.IMAP4_SSL(self.settings.netease_imap_host, self.settings.netease_imap_port,
                                      ssl_context=ssl.create_default_context(), timeout=30)
            client.login(self.settings.netease_email, self.settings.netease_email_auth_code.get_secret_value())
            if b"ID" in client.capabilities or "ID" in client.capabilities:
                imaplib.Commands.setdefault("ID", ("AUTH", "SELECTED"))
                client._simple_command("ID", '("name" "InterviewAssistant" "version" "1.0")')
            status, _ = client.select("INBOX", readonly=readonly)
            if status != "OK":
                raise ApplicationError("EMAIL_SELECT_FAILED", "无法打开收件箱。", status_code=502)
            yield client
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ApplicationError("EMAIL_CONNECTION_FAILED", "网易邮箱连接失败，请检查 IMAP 开启状态与授权码。", status_code=502) from exc
        finally:
            if client is not None:
                try:
                    client.logout()
                except (imaplib.IMAP4.error, OSError):
                    pass

    def messages(self, client, limit: int, scope: str = "unread"):
        """按范围返回邮件 UID 标识；用于去重的稳定键包含 UIDVALIDITY。

        参数:
            client: 已选择收件箱的 IMAP 连接。
            limit: 最多返回的最近邮件数量。
            scope: unread 表示未读，read 表示已读，all 表示全部。
        """
        criteria = {"unread": "UNSEEN", "read": "SEEN", "all": "ALL"}.get(scope)
        if criteria is None:
            raise ApplicationError("EMAIL_SCOPE_INVALID", "邮件扫描范围不合法。", status_code=422)
        status, values = client.uid("search", None, criteria)
        if status != "OK":
            raise ApplicationError("EMAIL_SEARCH_FAILED", "邮件查询失败。", status_code=502)
        # imaplib.response 会消费响应，只在同一个收件箱连接内缓存一次。
        validity = getattr(client, "_ia_uidvalidity", None)
        if not validity:
            validity_values = client.response("UIDVALIDITY")[1]
            if validity_values and validity_values[0]:
                validity = validity_values[0].decode()
            else:
                status, metadata = client.status("INBOX", "(UIDVALIDITY)")
                match = re.search(rb"UIDVALIDITY (\d+)", b" ".join(value for value in metadata if isinstance(value, bytes)))
                if status == "OK" and match:
                    validity = match[1].decode()
            if not validity or not str(validity).isdigit() or int(validity) <= 0:
                raise ApplicationError("EMAIL_UIDVALIDITY_MISSING", "邮箱未返回 UIDVALIDITY，无法安全去重。", status_code=502)
            client._ia_uidvalidity = validity
        result = []
        for uid in (values[0] or b"").split()[-limit:]:
            identity = f"{self.settings.netease_imap_host}:{self.settings.netease_email}:INBOX:{validity}:{uid.decode()}"
            result.append({"uid": uid.decode(), "receipt_id": sha256(identity.encode()).hexdigest()})
        return result

    def unread(self, client, limit: int):
        """兼容原调用方式，返回最近的未读邮件标识。"""
        return self.messages(client, limit, "unread")

    def fetch(self, client, uid: str) -> dict:
        """读取大小受限的邮件，不设置服务器上的已读标记 Seen。"""
        status, sizes = client.uid("fetch", uid, "(RFC822.SIZE)")
        match = re.search(rb"RFC822.SIZE (\d+)", b" ".join(value for value in sizes if isinstance(value, bytes)))
        if status != "OK" or not match or int(match[1]) > 2_000_000:
            raise ApplicationError("EMAIL_TOO_LARGE", "邮件过大或大小不可读取，保留未读。")
        status, parts = client.uid("fetch", uid, "(BODY.PEEK[])")
        raw = next((part[1] for part in parts if isinstance(part, tuple)), None)
        if status != "OK" or raw is None:
            raise ApplicationError("EMAIL_FETCH_FAILED", "邮件读取失败，保留未读。")
        message = BytesParser(policy=policy.default).parsebytes(raw)
        body = message.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body is not None else ""
        if body is not None and body.get_content_type() == "text/html":
            text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
        return {"subject": str(message.get("Subject", ""))[:1000], "sender": str(message.get("From", ""))[:1000],
                "date": str(message.get("Date", "")), "body": str(text)[:20000]}

    def mark_read(self, client, uid: str):
        """为一封已处理邮件的 UID 设置已读标记；失败时保留处理凭据以便重试。"""
        status, _ = client.uid("store", uid, "+FLAGS.SILENT", "(\\Seen)")
        if status != "OK":
            raise ApplicationError("EMAIL_MARK_FAILED", "邮件已处理，但标记已读失败。")
