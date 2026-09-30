"""全局配置：从 .env 读取，提供站点与 LLM 相关设置。"""

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

    # LLM 配置：留空则使用内置预设知识库回复；
    # 填入 Key 后自动切换为 OpenAI 兼容接口的真实模型调用
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-flash"

    # LLM 调用限制（防止 token 被恶意消耗）
    llm_max_tokens: int = 500              # 单次回复生成上限（token）
    chat_rate_limit: int = 10              # 每 IP 每分钟最大请求次数
    chat_daily_limit_per_ip: int = 30      # 每 IP 每日最大请求次数
    chat_daily_token_budget: int = 200000  # 全站每日 token 预算（估算），超出后降级预设知识库


settings = Settings()
