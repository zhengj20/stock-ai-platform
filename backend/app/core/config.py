"""应用配置模块"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
import os
import psutil


class Settings(BaseSettings):
    """应用配置项"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    APP_NAME: str = "A股智能分析平台"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # API配置
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS配置 - 生产环境通过环境变量覆盖
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]

    # 数据源配置
    SKILLS_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "skills")

    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_REQUIRED: bool = False
    CACHE_TTL: int = 300

    # 日志配置
    LOG_LEVEL: str = "INFO"

    # ===== 数据库配置 =====
    DB_PATH: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "app.db")
    DATABASE_URL: str = ""  # 由 model_post_init 自动生成

    # ===== JWT认证配置 =====
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ===== 限流配置 =====
    RATE_LIMIT_PER_MIN: int = 60

    # ===== Worker配置 =====
    WORKERS: int = psutil.cpu_count() or 4

    # ===== 管理员初始化 =====
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""  # 留空则首次启动随机生成并打印到日志
    INITIAL_INVITE_CODES: int = 5

    def model_post_init(self, __context):
        if not self.DATABASE_URL:
            self.DATABASE_URL = f"sqlite:///{self.DB_PATH}"
        if not self.SECRET_KEY:
            raise ValueError(
                "SECRET_KEY 未配置！请在 .env 中设置 SECRET_KEY，"
                "可用命令生成: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        # 密钥强度校验：至少 32 字符且不能是常见弱值
        weak_keys = {"", "secret", "key", "changeme", "replace-me-with-a-random-48-char-string"}
        if len(self.SECRET_KEY) < 32:
            raise ValueError(
                f"SECRET_KEY 强度不足（当前 {len(self.SECRET_KEY)} 字符，至少需要 32），"
                "可用命令生成: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        if self.SECRET_KEY.lower() in weak_keys:
            raise ValueError("SECRET_KEY 使用了弱密钥，请更换为随机生成的强密钥")


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()

