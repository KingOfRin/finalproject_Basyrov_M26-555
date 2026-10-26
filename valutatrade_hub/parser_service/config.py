"""Конфигурация Parser Service: API-ключи, эндпоинты, списки валют, пути.

API-ключ ExchangeRate-API не хранится в коде: он читается из переменной
окружения EXCHANGERATE_API_KEY. Для удобства ключ можно положить в файл
.env в корне проекта (файл исключён из git):

    EXCHANGERATE_API_KEY=3b47a9b92e1b14c1f1234567
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader

API_KEY_ENV = "EXCHANGERATE_API_KEY"
ENV_FILE_NAME = ".env"


def load_env_file(path: Path) -> None:
    """Загружает KEY=VALUE из .env в os.environ (не перезаписывая заданные)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _api_key() -> str | None:
    load_env_file(SettingsLoader().project_root / ENV_FILE_NAME)
    return os.getenv(API_KEY_ENV) or None


def _settings_path(key: str) -> str:
    return str(SettingsLoader().get_path(key))


@dataclass
class ParserConfig:
    """Все изменяемые параметры Parser Service в одном месте."""

    # Ключ загружается из переменной окружения (или .env)
    EXCHANGERATE_API_KEY: str | None = field(default_factory=_api_key)

    # Эндпоинты
    COINGECKO_URL: str = "https://api.coingecko.com/api/v3/simple/price"
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6"

    # Списки валют
    BASE_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple = ("EUR", "GBP", "RUB", "CNY")
    CRYPTO_CURRENCIES: tuple = ("BTC", "ETH", "SOL")
    CRYPTO_ID_MAP: dict = field(
        default_factory=lambda: {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
        }
    )

    # Пути (берутся из SettingsLoader, чтобы Core и Parser читали одни файлы)
    RATES_FILE_PATH: str = field(default_factory=lambda: _settings_path("rates_file"))
    HISTORY_FILE_PATH: str = field(
        default_factory=lambda: _settings_path("exchange_rates_file")
    )

    # Сетевые параметры
    REQUEST_TIMEOUT: int = 10
    UPDATE_INTERVAL_SECONDS: int = field(
        default_factory=lambda: int(
            SettingsLoader().get("parser_update_interval_seconds")
        )
    )
