"""提供 OpenAI 格式的错误响应，不暴露模型供应商凭证或响应正文。"""


class AgentError(Exception):
    """可安全展示给桌面客户端的预期 Agent 异常。"""

    def __init__(
        self, message: str, code: str, status_code: int = 502,
        error_type: str = "server_error", param: str | None = None,
    ) -> None:
        """保存公开错误信息、固定错误码、HTTP 状态码和可选字段名。"""
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.error_type = error_type
        self.param = param

    def as_dict(self) -> dict:
        """返回 OpenAI 兼容客户端可识别的错误对象。"""
        return {"error": {
            "message": self.message, "type": self.error_type,
            "param": self.param, "code": self.code,
        }}
