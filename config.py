import os
from pydantic_settings import BaseSettings


def _get_port() -> int:
    p = os.environ.get("PORT")
    if p and p.isdigit():
        return int(p)
    return 8000


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Scan
    scan_interval_minutes: int = 180

    # Web
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    web_api_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        rp = _get_port()
        if rp != 8000:
            self.web_port = rp


settings = Settings()
