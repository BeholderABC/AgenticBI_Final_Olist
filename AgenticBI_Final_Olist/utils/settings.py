from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
ARTIFACTS_DIR = DATA_DIR / "artifacts"

DEFAULT_DEEPSEEK_API_KEY = "sk-f1da75d5e90945daa3de76ad9791c8a4"


@dataclass(frozen=True)
class AppSettings:
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str


def get_settings() -> AppSettings:
    load_dotenv(dotenv_path=ROOT_DIR / ".env", override=False)

    return AppSettings(
        mysql_host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
        mysql_user=os.getenv("MYSQL_USER", "root"),
        mysql_password=os.getenv("MYSQL_PASSWORD", ""),
        mysql_database=os.getenv("MYSQL_DATABASE", "olist_agentic_bi"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", DEFAULT_DEEPSEEK_API_KEY),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    )

