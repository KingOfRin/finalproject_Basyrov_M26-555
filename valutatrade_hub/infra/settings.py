"""SettingsLoader — единственная точка доступа к конфигурации (Singleton).

Источник конфигурации — секция [tool.valutatrade] в pyproject.toml.
Если файла нет (например, пакет установлен через uv tool install),
используются значения по умолчанию, а корнем считается текущий каталог.

Ключи конфигурации:
    data_dir, users_file, portfolios_file, rates_file, exchange_rates_file —
        пути к JSON-хранилищу (относительно корня проекта);
    rates_ttl_seconds — сколько секунд курс в rates.json считается свежим;
    default_base_currency — базовая валюта по умолчанию;
    log_dir, actions_log_file, parser_log_file — пути к логам;
    log_level, log_format, log_date_format — уровень и формат логов;
    log_max_bytes, log_backup_count — политика ротации логов;
    parser_update_interval_seconds — период автообновления курсов.

Переменные окружения:
    VALUTATRADE_HOME — переопределяет корень проекта;
    VALUTATRADE_LOG_LEVEL — переопределяет log_level (например, DEBUG).
"""

import os
import tomllib
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "data_dir": "data",
    "users_file": "data/users.json",
    "portfolios_file": "data/portfolios.json",
    "rates_file": "data/rates.json",
    "exchange_rates_file": "data/exchange_rates.json",
    "rates_ttl_seconds": 300,
    "default_base_currency": "USD",
    "log_dir": "logs",
    "actions_log_file": "logs/actions.log",
    "parser_log_file": "logs/parser.log",
    "log_level": "INFO",
    "log_format": "%(levelname)s %(asctime)s %(message)s",
    "log_date_format": "%Y-%m-%dT%H:%M:%S",
    "log_max_bytes": 1_048_576,
    "log_backup_count": 5,
    "parser_update_interval_seconds": 300,
}

_MISSING = object()


def _find_project_root() -> Path:
    env_home = os.getenv("VALUTATRADE_HOME")
    if env_home:
        return Path(env_home).resolve()
    package_root = Path(__file__).resolve().parents[2]
    if (package_root / "pyproject.toml").exists():
        return package_root
    return Path.cwd()


class SettingsLoader:
    """Загружает и кеширует конфигурацию проекта.

    Singleton реализован через __new__: это самый короткий и читаемый способ —
    не нужен метакласс, а повторный вызов SettingsLoader() в любом модуле
    возвращает тот же объект без повторного чтения pyproject.toml.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._config = {}
            instance._root = _find_project_root()
            instance._load()
            cls._instance = instance
        return cls._instance

    def _load(self) -> None:
        config = dict(DEFAULTS)
        pyproject = self._root / "pyproject.toml"
        if pyproject.exists():
            with pyproject.open("rb") as file:
                section = tomllib.load(file).get("tool", {}).get("valutatrade", {})
            config.update(section)
        env_level = os.getenv("VALUTATRADE_LOG_LEVEL")
        if env_level:
            config["log_level"] = env_level.upper()
        self._config = config

    @property
    def project_root(self) -> Path:
        """Корневой каталог проекта, от которого считаются относительные пути."""
        return self._root

    def get(self, key: str, default: Any = _MISSING) -> Any:
        """Возвращает значение ключа конфигурации.

        Raises:
            KeyError: если ключа нет и default не передан.
        """
        if key in self._config:
            return self._config[key]
        if default is _MISSING:
            raise KeyError(f"Неизвестный ключ конфигурации '{key}'")
        return default

    def get_path(self, key: str) -> Path:
        """Возвращает абсолютный путь для ключа-пути (относительно корня)."""
        path = Path(self.get(key))
        return path if path.is_absolute() else self._root / path

    def reload(self) -> None:
        """Перечитывает конфигурацию с диска."""
        self._root = _find_project_root()
        self._load()
