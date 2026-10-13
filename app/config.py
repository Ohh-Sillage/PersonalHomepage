"""全局配置：从 .env 读取站点通用设置。

说明：AI 助手相关配置（LLM/CHAT/RESUME/ALERT_SMTP）已迁入独立模块
assistant/config.py 的 AIConfig（读取同一份 .env，变量名不变）。
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（app/ 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """应用配置，可通过 .env 或环境变量覆盖。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 站点
    site_url: str = "https://yjgnet.cn"


settings = Settings()
