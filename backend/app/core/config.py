from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """从 backend/.env 和环境变量加载的运行配置。"""
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Interview Assistant API"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    docs_enabled: bool = True
    api_prefix: str = "/api"
    log_level: str = "INFO"

    langgraph_sqlite_path: Path = BACKEND_DIR / "data" / "langgraph.sqlite3"
    interviews_file_path: Path = BACKEND_DIR / "data" / "interviews.md"
    local_state_path: Path = BACKEND_DIR / "data" / "runtime.json"
    resume_storage_path: Path = BACKEND_DIR / "data" / "resumes"

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    agent_model_name: str = "interview-assistant"
    agent_timeout_seconds: float = Field(default=120.0, gt=0)
    agent_max_tool_rounds: int = Field(default=4, ge=1, le=10)
    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_environment: str = Field(
        default="development",
        validation_alias=AliasChoices("LANGFUSE_TRACING_ENVIRONMENT", "LANGFUSE_ENVIRONMENT"),
        pattern=r"^[a-z0-9_-]{1,40}$",
    )
    langfuse_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    langfuse_capture_content: bool = False
    netease_imap_host: str = "imap.163.com"
    netease_imap_port: int = 993
    netease_email: str | None = None
    netease_email_auth_code: SecretStr | None = None
    boss_profile_path: Path = BACKEND_DIR / "data" / "boss-profile"
    boss_browser_channel: str = "chrome"
    jobs_max_candidates: int = Field(default=10, ge=1, le=30)
    jobs_pages_per_query: int = Field(default=2, ge=1, le=5)
    jobs_max_search_pages: int = Field(default=6, ge=1, le=30)
    jobs_browser_settle_seconds: float = Field(default=8.0, ge=3.0, le=30.0)
    jobs_request_interval_seconds: float = Field(default=3.0, ge=1.0, le=60.0)
    mock_interview_max_questions: int = Field(default=8, ge=1, le=20)

    request_timeout_seconds: float = Field(default=30.0, gt=0)

    @field_validator("langfuse_environment")
    @classmethod
    def validate_langfuse_environment(cls, value: str) -> str:
        """Langfuse 保留以 langfuse 开头的环境名。"""
        if value.startswith("langfuse"):
            raise ValueError("Langfuse 环境名不能以 langfuse 开头")
        return value

    @field_validator("langgraph_sqlite_path", "interviews_file_path", "local_state_path", "resume_storage_path", "boss_profile_path", mode="before")
    @classmethod
    def resolve_local_path(cls, value: str | Path) -> Path:
        """以 backend 目录为基准解析状态文件或浏览器配置目录的相对路径。
        
        参数:
            value: 绝对路径，或相对于 backend 目录的路径。
        
        返回值:
            对应配置项的绝对文件系统路径。
        """
        path = Path(value)
        return path if path.is_absolute() else BACKEND_DIR / path


@lru_cache
def get_settings() -> Settings:
    """返回进程内缓存的配置对象。"""
    return Settings()
