from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Scan
    scan_interval_minutes: int = 30

    # Web
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    web_api_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
